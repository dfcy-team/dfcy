from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models

from apps.tenants.models import Department, Tenant


class CustomUserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, username, email="", password=None, **extra_fields):
        if not username:
            raise ValueError("The username must be set.")
        email = self.normalize_email(email)
        user = self.model(username=username, email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, email="", password=None, **extra_fields):
        extra_fields.setdefault("user_type", CustomUser.UserType.INTERNAL)
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(username, email, password, **extra_fields)


class CustomUser(AbstractBaseUser, PermissionsMixin):
    class UserType(models.TextChoices):
        INTERNAL = "internal", "Internal"
        EXTERNAL = "external", "External"
        RPA = "rpa", "RPA"

    username = models.CharField(max_length=150, unique=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=32, blank=True)
    user_type = models.CharField(max_length=20, choices=UserType.choices)
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="users")
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = CustomUserManager()

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = ["email", "tenant_id", "user_type"]

    class Meta:
        ordering = ["username"]

    def __str__(self):
        return self.username


class InternalUserProfile(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name="internal_profile")
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="internal_profiles")
    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="internal_profiles",
    )
    employee_no = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} internal profile"


class ExternalUserProfile(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name="external_profile")
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="external_profiles")
    supplier_id = models.BigIntegerField(null=True, blank=True)
    company_name = models.CharField(max_length=100, blank=True)
    contact_name = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} external profile"
