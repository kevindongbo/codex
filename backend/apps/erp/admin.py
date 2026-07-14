from django.contrib import admin

from .models import Organization, Membership, Warehouse, Product, SKU, Supplier

admin.site.register([Organization, Membership, Warehouse, Product, SKU, Supplier])
