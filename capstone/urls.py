from django.contrib import admin
from django.urls import path, include # 必须加 include

urlpatterns = [
    path('admin/', admin.site.urls),
   
    path('', include('stock.urls')), 
]