from pathlib import Path
from decouple import config, Csv

# /root/brains/eos
BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = config('SECRET_KEY', default='dev-secret-key-change-in-production-please')

DEBUG = config('DEBUG', default=True, cast=bool)

ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1', cast=Csv())

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django_otp',
    'django_otp.plugins.otp_totp',
    'django_otp.plugins.otp_static',
    'rest_framework',
    'drf_spectacular',
    'drf_spectacular_sidecar',
    'oauth2_provider',
    # Feature modules — uncommented as each phase is built
    'apps.accounts',
    'apps.audit',
    'apps.rocks',
    'apps.issues',
    'apps.todos',
    'apps.scorecards',
    'apps.vision',
    'apps.accountability',
    'apps.meetings',
    'apps.notifications',
    'apps.api',
    # 'apps.todos',
    # 'apps.vision',
    # 'apps.scorecards',
    # 'apps.accountability',
    # 'apps.meetings',
]

# Deployments can enable third-party or private apps without forking, e.g.
# EXTRA_INSTALLED_APPS=django.contrib.sites,my_company.sso
INSTALLED_APPS += config('EXTRA_INSTALLED_APPS', default='', cast=Csv())

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'apps.accounts.middleware.OrganizationDomainMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'django_otp.middleware.OTPMiddleware',
    'apps.accounts.two_factor.middleware.TwoFactorRequiredMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'apps.accounts.context_processors.active_context',
                'apps.accounts.context_processors.branding',
                'apps.accounts.context_processors.terminology',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('DB_NAME', default='epd_db'),
        'USER': config('DB_USER', default='epd_user'),
        'PASSWORD': config('DB_PASSWORD', default='epd_password'),
        'HOST': config('DB_HOST', default='localhost'),
        'PORT': config('DB_PORT', default='5432'),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
}

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'mediafiles'
# Avatars are served through a permission-checked view. When a proxy such as
# Nginx sits in front, let it send the bytes via X-Accel-Redirect instead of Django.
MEDIA_ACCEL_REDIRECT = config('MEDIA_ACCEL_REDIRECT', default=False, cast=bool)

# Largest organisation archive the browser export will build. Bigger ones are
# exported on the server with manage.py export_organization, which has no limit.
EXPORT_MAX_BYTES = config('EXPORT_MAX_BYTES', default=500 * 1024 * 1024, cast=int)

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/accounts/login/'

# Shown as the account label in authenticator apps.
OTP_TOTP_ISSUER = config('OTP_TOTP_ISSUER', default='Empresadence')

# ── Email ────────────────────────────────────────────────────────────────────
# Set EMAIL_HOST to enable SMTP; otherwise emails print to the console (dev-friendly default).
EMAIL_HOST = config('EMAIL_HOST', default='')
if EMAIL_HOST:
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
    EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
    EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
    EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
else:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default='Empresadence <noreply@example.com>')

# Base URL used to build absolute links in emails (no trailing slash).
SITE_URL = config('SITE_URL', default='http://localhost:8000')

# Name shown in the navbar, page titles and emails when no organisation
# branding applies (the main host's login page, for instance).
DEFAULT_BRAND_NAME = config('BRAND_NAME', default='Empresadence')

# ── REST API ─────────────────────────────────────────────────────────────────
# Served under /api/v1/. Only OAuth 2.1 access tokens are accepted: there is no
# session authentication, so a browser cookie never reaches the API and
# cross-site request forgery stays out of scope.
API_THROTTLE_RATE = config('API_THROTTLE_RATE', default='600/min')

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': ['apps.api.authentication.ApiTokenAuthentication'],
    'DEFAULT_PERMISSION_CLASSES': ['apps.api.permissions.TokenHasScope'],
    'DEFAULT_THROTTLE_CLASSES': ['apps.api.throttling.TokenRateThrottle'],
    'DEFAULT_THROTTLE_RATES': {'token': API_THROTTLE_RATE},
    'DEFAULT_RENDERER_CLASSES': ['rest_framework.renderers.JSONRenderer'],
    'DEFAULT_PARSER_CLASSES': ['rest_framework.parsers.JSONParser'],
    'DEFAULT_PAGINATION_CLASS': 'apps.api.pagination.ApiCursorPagination',
    'DEFAULT_SCHEMA_CLASS': 'apps.api.schema.ApiAutoSchema',
    'EXCEPTION_HANDLER': 'apps.api.exceptions.problem_details_handler',
}

SPECTACULAR_SETTINGS = {
    'TITLE': 'Empresadence API',
    'DESCRIPTION': (
        'Read access to one organisation\'s teams, priorities, actions, blockers, metrics boards, '
        'meetings, vision document and org chart. '
        'Every request needs an OAuth 2.1 access token; the token fixes the organisation '
        'it acts in. Resource and field names are fixed whatever an organisation calls '
        'things: its own words are returned by `GET /api/v1/organisation`.'
    ),
    'VERSION': '1.0.0',
    # Set to '3.1.0' if a client cannot read 3.2 yet; nothing else needs to change.
    'OAS_VERSION': '3.2.0',
    'SCHEMA_PATH_PREFIX': '/api/v1',
    'SERVE_INCLUDE_SCHEMA': False,
    'SERVE_PERMISSIONS': ['rest_framework.permissions.AllowAny'],
    'SERVE_AUTHENTICATION': [],
    'COMPONENT_SPLIT_REQUEST': True,
    'SORT_OPERATION_PARAMETERS': True,
    # The docs page is served from the application's own static files.
    'SWAGGER_UI_DIST': 'SIDECAR',
    'SWAGGER_UI_FAVICON_HREF': 'SIDECAR',
    'REDOC_DIST': 'SIDECAR',
    'SWAGGER_UI_SETTINGS': {'deepLinking': True, 'persistAuthorization': False},
    'SWAGGER_UI_OAUTH2_CONFIG': {'usePkceWithAuthorizationCodeGrant': True},
    'OAUTH2_FLOWS': ['authorizationCode'],
    'OAUTH2_AUTHORIZATION_URL': '/o/authorize/',
    'OAUTH2_TOKEN_URL': '/o/token/',
    'OAUTH2_REFRESH_URL': '/o/token/',
    'TAGS': [
        {'name': 'Organisation', 'description': 'The organisation the token acts in, and the caller.'},
        {'name': 'Teams'},
        {'name': 'Priorities', 'description': 'Quarterly priorities.'},
        {'name': 'Steps', 'parent': 'Priorities', 'description': 'The steps that make up a priority.'},
        {'name': 'Check-ins', 'parent': 'Priorities', 'description': 'Weekly progress notes on a priority.'},
        {'name': 'Actions'},
        {'name': 'Blockers'},
        {'name': 'Metrics Boards', 'description': 'The numbers a team watches each week or month.'},
        {'name': 'Metrics', 'parent': 'Metrics Boards', 'description': 'The measures on a board, each with a goal.'},
        {'name': 'Entries', 'parent': 'Metrics Boards', 'description': 'The value entered for a metric each period.'},
        {'name': 'Meetings', 'description': 'A team\'s regular meetings, with what was noted and agreed.'},
        {'name': 'Vision Board', 'description': 'The organisation\'s long-term vision and plan.'},
        {'name': 'Org Chart', 'description': 'Who is responsible for what.'},
    ],
    'POSTPROCESSING_HOOKS': [
        'drf_spectacular.hooks.postprocess_schema_enums',
        'apps.api.schema.add_oauth2_metadata_url',
    ],
    'ENUM_NAME_OVERRIDES': {
        'PriorityStatusEnum': 'apps.api.serializers.PRIORITY_STATUSES',
        'ActionStatusEnum': 'apps.api.serializers.ACTION_STATUSES',
        'BlockerStatusEnum': 'apps.api.serializers.BLOCKER_STATUSES',
        'ConfidenceEnum': 'apps.api.serializers.CONFIDENCE_CHOICES',
        'QuarterEnum': 'apps.api.serializers.QUARTERS',
        'MetricFrequencyEnum': 'apps.api.serializers.METRIC_FREQUENCIES',
        'MeetingStatusEnum': 'apps.api.serializers.MEETING_STATUSES',
        'SectionFormatEnum': 'apps.api.serializers.SECTION_FORMATS',
    },
}

# ── OAuth 2.1 authorisation server ───────────────────────────────────────────
# django-oauth-toolkit, with the settings OAuth 2.1 and RFC 9700 ask for switched
# on: authorisation code with PKCE (S256) only, tokens stored hashed, refresh
# tokens rotated with replay detection, and the issuer returned to the client.
# The library's models are swappable. They are not swapped here, but the
# migrations of apps.api point at them through these names, so they must be set.
OAUTH2_PROVIDER_APPLICATION_MODEL = 'oauth2_provider.Application'
OAUTH2_PROVIDER_GRANT_MODEL = 'oauth2_provider.Grant'
OAUTH2_PROVIDER_ACCESS_TOKEN_MODEL = 'oauth2_provider.AccessToken'
OAUTH2_PROVIDER_REFRESH_TOKEN_MODEL = 'oauth2_provider.RefreshToken'

OAUTH2_PROVIDER = {
    'OAUTH2_VALIDATOR_CLASS': 'apps.api.oauth_validators.ApiOAuth2Validator',
    'SCOPES_BACKEND_CLASS': 'apps.api.scopes.ApiScopes',
    'PKCE_REQUIRED': True,
    'AUTHORIZATION_CODE_EXPIRE_SECONDS': 60,
    'ACCESS_TOKEN_EXPIRE_SECONDS': config('API_ACCESS_TOKEN_SECONDS', default=3600, cast=int),
    'REFRESH_TOKEN_EXPIRE_SECONDS': config('API_REFRESH_TOKEN_SECONDS', default=30 * 24 * 3600, cast=int),
    'ROTATE_REFRESH_TOKEN': True,
    'REFRESH_TOKEN_REUSE_PROTECTION': True,
    # Must stay 0: a retried refresh inside a grace period is answered from the
    # stored token, and hashed storage keeps no token to answer with.
    'REFRESH_TOKEN_GRACE_PERIOD_SECONDS': 0,
    'REQUEST_APPROVAL_PROMPT': 'force',
    # http is kept for the loopback redirects native and command-line clients
    # use (RFC 8252); the validator refuses http for any other host.
    'ALLOWED_REDIRECT_URI_SCHEMES': ['https', 'http'],
    'ALLOW_URI_WILDCARDS': False,
    'COMPLIANT_BCP_RFC9700_IMPLICIT_GRANT': True,
    'COMPLIANT_BCP_RFC9700_PASSWORD_GRANT': True,
    'COMPLIANT_BCP_RFC9700_PKCE_METHOD': True,
    'COMPLIANT_BCP_RFC9700_ACCESS_TOKEN_TRANSPORT': True,
    'COMPLIANT_BCP_RFC9700_AUTHZ_RESPONSE_ISS': True,
    'COMPLIANT_BCP_RFC9700_TOKEN_STORAGE': True,
    'COMPLIANT_BCP_RFC9700_REFRESH_TOKEN': True,
    'COMPLIANT_BCP_RFC9700_REDIRECT_URI_MATCHING': True,
    'COMPLIANT_BCP_RFC9700_PKCE_REQUIRED': True,
    # Left off because http stays allowed for loopback redirects (see above).
    'COMPLIANT_BCP_RFC9700_REDIRECT_URI_SCHEME': False,
    'OAUTH2_RESPONSE_TYPES_SUPPORTED': ['code'],
    'OAUTH2_GRANT_TYPES_SUPPORTED': ['authorization_code', 'refresh_token'],
    'OAUTH2_TOKEN_ENDPOINT_AUTH_METHODS_SUPPORTED': ['none', 'client_secret_basic', 'client_secret_post'],
    'OAUTH2_PROTECTED_RESOURCE_NAME': config('API_RESOURCE_NAME', default='Empresadence API'),
    # Clients are registered in advance. Dynamic Client Registration stays off,
    # and Client ID Metadata Documents wait for the MCP server.
    'DCR_ENABLED': False,
    'CIMD_ENABLED': False,
}
