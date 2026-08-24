from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models.expressions import BaseExpression


class ValidatedQuerySet(models.QuerySet):
    def bulk_create(self, objs, *args, **kwargs):
        objects = list(objs)
        for obj in objects:
            obj.full_clean()
        return super().bulk_create(objects, *args, **kwargs)

    def bulk_update(self, objs, fields, *args, **kwargs):
        objects = list(objs)
        if any(obj.pk is None for obj in objects):
            raise ValueError("All bulk_update objects must have a primary key.")
        with transaction.atomic(using=self.db):
            for obj in objects:
                obj.save(using=self.db, update_fields=fields)
        return len(objects)

    def update(self, **kwargs):
        if any(isinstance(value, BaseExpression) for value in kwargs.values()):
            raise ValidationError("Expression updates are disabled for validated models.")
        updated = 0
        with transaction.atomic(using=self.db):
            for obj in self.select_for_update():
                for field_name, value in kwargs.items():
                    field = obj._meta.get_field(field_name)
                    if field.is_relation and value is not None and not isinstance(value, models.Model):
                        setattr(obj, field.attname, value)
                    else:
                        setattr(obj, field_name, value)
                obj.save(using=self.db, update_fields=kwargs.keys())
                updated += 1
        return updated


class ValidatedManager(models.Manager.from_queryset(ValidatedQuerySet)):
    pass


class ValidatedWriteModel(models.Model):
    objects = ValidatedManager()

    class Meta:
        abstract = True
        base_manager_name = "objects"
        default_manager_name = "objects"

    def validated_update_fields(self, update_fields):
        return update_fields

    def save(self, *args, **kwargs):
        self.full_clean()
        if "update_fields" in kwargs:
            kwargs["update_fields"] = self.validated_update_fields(kwargs["update_fields"])
        return super().save(*args, **kwargs)
