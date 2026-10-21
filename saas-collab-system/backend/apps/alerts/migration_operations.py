"""Online index DDL on PostgreSQL; standard Django behavior on other engines."""
from django.db import migrations


class OnlineAddIndex(migrations.AddIndex):
    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor != 'postgresql':
            return super().database_forwards(app_label, schema_editor, from_state, to_state)
        model = to_state.apps.get_model(app_label, self.model_name)
        if self.allow_migrate_model(schema_editor.connection.alias, model):
            schema_editor.add_index(model, self.index, concurrently=True)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor != 'postgresql':
            return super().database_backwards(app_label, schema_editor, from_state, to_state)
        model = from_state.apps.get_model(app_label, self.model_name)
        if self.allow_migrate_model(schema_editor.connection.alias, model):
            schema_editor.remove_index(model, self.index, concurrently=True)


class OnlineRemoveIndex(migrations.RemoveIndex):
    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor != 'postgresql':
            return super().database_forwards(app_label, schema_editor, from_state, to_state)
        model = from_state.apps.get_model(app_label, self.model_name)
        if self.allow_migrate_model(schema_editor.connection.alias, model):
            index = from_state.models[app_label, self.model_name_lower].get_index_by_name(self.name)
            schema_editor.remove_index(model, index, concurrently=True)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor != 'postgresql':
            return super().database_backwards(app_label, schema_editor, from_state, to_state)
        model = to_state.apps.get_model(app_label, self.model_name)
        if self.allow_migrate_model(schema_editor.connection.alias, model):
            index = to_state.models[app_label, self.model_name_lower].get_index_by_name(self.name)
            schema_editor.add_index(model, index, concurrently=True)
