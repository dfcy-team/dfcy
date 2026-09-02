from django.contrib import admin

from .models import CountrySiteMaster, PlatformMaster, PlatformSiteMaster, StoreMaster, SupplierMaster, WarehouseMaster


for model in (PlatformMaster, PlatformSiteMaster, StoreMaster, CountrySiteMaster, WarehouseMaster, SupplierMaster):
    admin.site.register(model)
