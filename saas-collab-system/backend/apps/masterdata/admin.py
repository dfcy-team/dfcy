from django.contrib import admin

from .models import PlatformMaster, StoreMaster, SupplierMaster, WarehouseMaster


for model in (PlatformMaster, StoreMaster, WarehouseMaster, SupplierMaster):
    admin.site.register(model)
