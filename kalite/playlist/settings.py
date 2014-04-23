try:
    import local_settings
except ImportError:
    local_settings = object()

INSTALLED_APPS = getattr(local_settings, 'INSTALLED_APPS', tuple())
INSTALLED_APPS = ("tastypie") + INSTALLED_APPS