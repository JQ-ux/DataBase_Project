from django.urls import path
from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("portfolio/", views.portfolio_view, name="portfolio"),
    path("transactions/", views.transactions_view, name="transactions"),

    path("login/", views.login_view, name="login"),
    path("register/", views.register_view, name="register"),
    path("logout/", views.logout_view, name="logout"),

    path("api/search/", views.api_search, name="api_search"),
    path("api/trade/", views.process_transaction, name="process_transaction"),

    path("stock/<str:symbol>/", views.stock_detail, name="stock_detail"),
    path("stock/<str:symbol>/financials/", views.company_financials, name="company_financials"),
    path("stock/<str:symbol>/history/", views.stock_history_full, name="stock_history"), 
    
    path("simulation/<int:sim_id>/report/", views.simulation_performance, name="simulation_performance"),
]