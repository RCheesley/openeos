"""The small trend chart shown beside each metric on the board.

The chart is an inline SVG drawn by the server from the periods the board
shows, with no script and no outside asset. ``build_trend`` works out the
geometry and the sentence that stands in for the picture;
``templates/scorecards/_sparkline.html`` writes the markup.
"""
from .models import ScorecardMetric, period_column_label

WIDTH = 104
HEIGHT = 28
PAD = 4

# A fitted change smaller than this share of the largest value counts as steady,
# so a number that wobbles by a percent or two is not called rising or falling.
STEADY_SHARE = 0.05

RISING, FALLING, STEADY = 'rising', 'falling', 'steady'

_PERIOD_NOUNS = {
    ScorecardMetric.FREQ_WEEKLY: ('week', 'weeks'),
    ScorecardMetric.FREQ_MONTHLY: ('month', 'months'),
    ScorecardMetric.FREQ_QUARTERLY: ('quarter', 'quarters'),
    ScorecardMetric.FREQ_ANNUAL: ('year', 'years'),
}
_GOAL_WORDS = {
    ScorecardMetric.DIR_ABOVE: 'at least',
    ScorecardMetric.DIR_BELOW: 'at most',
    ScorecardMetric.DIR_EQUAL: 'exactly',
}


def trend_direction(values):
    """Return rising, falling or steady for a series with gaps, or None under two values.

    A straight line is fitted through the entered values (least squares, each
    value placed at its period, so a gap counts as time passing) and the
    change along that line from the first entered period to the last is
    compared with the size of the numbers.
    """
    points = [(i, float(v)) for i, v in enumerate(values) if v is not None]
    if len(points) < 2:
        return None
    n = len(points)
    mean_x = sum(x for x, _ in points) / n
    mean_y = sum(y for _, y in points) / n
    spread = sum((x - mean_x) ** 2 for x, _ in points)
    slope = sum((x - mean_x) * (y - mean_y) for x, y in points) / spread
    change = slope * (points[-1][0] - points[0][0])
    scale = max(abs(y) for _, y in points)
    if scale == 0 or abs(change) < STEADY_SHARE * scale:
        return STEADY
    return RISING if change > 0 else FALLING


def _reference_lines(metric):
    """Return (goal, [warning values]) as floats. An exact goal has a warning line each side."""
    goal = float(metric.goal_value)
    if metric.warning_value is None:
        return goal, []
    if metric.goal_direction == ScorecardMetric.DIR_EQUAL:
        tolerance = float(metric.warning_tolerance)
        return goal, [goal - tolerance, goal + tolerance]
    return goal, [float(metric.warning_value)]


def _goal_phrase(metric):
    phrase = f'a goal of {_GOAL_WORDS[metric.goal_direction]} {metric.format_value(metric.goal_value)}'
    if metric.warning_value is not None:
        phrase += f' ({metric.format_warning().lower()})'
    return phrase


def trend_text(metric, periods, values):
    """The sentence that describes the chart: direction, latest value and goal."""
    singular, plural = _PERIOD_NOUNS[metric.frequency]
    span = f'the last {len(periods)} {plural}' if len(periods) != 1 else f'the last {singular}'
    entered = [(p, v) for p, v in zip(periods, values) if v is not None]
    goal = _goal_phrase(metric)
    if not entered:
        return f'No values entered in {span}, against {goal}.'
    latest_period, latest_value = entered[-1]
    latest = metric.format_value(latest_value)
    if latest_period != periods[-1]:
        # Say which period the latest number is from when it is not the current one.
        latest += f' ({period_column_label(metric.frequency, latest_period)})'
    if len(entered) == 1:
        return f'One value entered in {span}: {latest} against {goal}.'
    direction = trend_direction(values).capitalize()
    return f'{direction} over {span}, latest {latest} against {goal}.'


def _fmt(number):
    """A coordinate with at most one decimal place and no trailing zero."""
    return f'{number:.1f}'.rstrip('0').rstrip('.')


def build_trend(metric, periods, cells):
    """Return what the sparkline template needs for one metric.

    ``cells`` is the board's row: one entry or None for each of ``periods``.
    A period with no entry is a gap in the line, never a zero: the line is
    drawn as separate runs, and a value with a gap on both sides as a dot.
    """
    values = [cell.value if cell else None for cell in cells]
    goal, warnings = _reference_lines(metric)
    numbers = [float(v) for v in values if v is not None]
    low = min(numbers + [goal] + warnings)
    high = max(numbers + [goal] + warnings)

    def x_at(index):
        if len(periods) < 2:
            return WIDTH / 2
        return PAD + index * (WIDTH - 2 * PAD) / (len(periods) - 1)

    def y_at(value):
        if high == low:
            return HEIGHT / 2
        return HEIGHT - PAD - (float(value) - low) / (high - low) * (HEIGHT - 2 * PAD)

    runs, run = [], []
    for index, value in enumerate(values):
        if value is None:
            if run:
                runs.append(run)
            run = []
        else:
            run.append((x_at(index), y_at(value)))
    if run:
        runs.append(run)

    latest = runs[-1][-1] if runs else None
    return {
        'width': WIDTH,
        'height': HEIGHT,
        'x1': _fmt(PAD / 2),
        'x2': _fmt(WIDTH - PAD / 2),
        'goal_y': _fmt(y_at(goal)),
        'warning_ys': [_fmt(y_at(w)) for w in warnings],
        'lines': [' '.join(f'{_fmt(x)},{_fmt(y)}' for x, y in r) for r in runs if len(r) > 1],
        'dots': [{'x': _fmt(r[0][0]), 'y': _fmt(r[0][1])} for r in runs if len(r) == 1],
        'latest': {'x': _fmt(latest[0]), 'y': _fmt(latest[1])} if latest else None,
        'direction': trend_direction(values),
        'text': trend_text(metric, periods, values),
    }
