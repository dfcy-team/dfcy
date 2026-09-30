# OAuth callbacks contain one-use credentials in their query string. Use the
# URL path atom rather than the default full request-line atom in access logs.
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(m)s %(U)s %(H)s" %(s)s %(b)s'
