from django.db import migrations


PERMISSIONS = (
    ("products.category.view", "查看商品分类", "products", "category.view", "查看当前租户的商品分类。"),
    ("products.category.manage", "维护商品分类", "products", "category.manage", "新增和维护商品三级分类。"),
    ("products.color.view", "查看颜色字典", "products", "color.view", "查看当前租户的颜色编码字典。"),
    ("products.color.manage", "维护颜色字典", "products", "color.manage", "新增和维护颜色编码。"),
    ("products.attribute.view", "查看商品属性", "products", "attribute.view", "查看末级分类的 SKU 属性定义。"),
    ("products.attribute.manage", "维护商品属性", "products", "attribute.manage", "维护末级分类的 SKU 属性及编码顺序。"),
    ("products.specification.view", "查看商品规格", "products", "specification.view", "查看末级分类的 SKU 规格维度。"),
    ("products.specification.manage", "维护商品规格", "products", "specification.manage", "维护末级分类的 SKU 规格维度及编码顺序。"),
    ("products.bundle.view", "查看组合商品", "products", "bundle.view", "查看由现有 SKU 组成的组合 SKU。"),
    ("products.bundle.manage", "维护组合商品", "products", "bundle.manage", "创建组合 SKU 并维护其现有 SKU 组成明细。"),
    ("listings.workbench.view", "查看全球刊登工作台", "listings", "workbench.view", "查看租户范围内的全球刊登商品、店铺和模板选择器。"),
    ("listings.workbench.manage", "管理全球刊登工作台", "listings", "workbench.manage", "批量生成租户范围内的刊登草稿。"),
    ("listings.mapping.view", "查看平台类目与属性映射", "listings", "mapping.view", "查看租户范围内的平台类目及商品属性映射。"),
    ("listings.mapping.manage", "维护平台类目与属性映射", "listings", "mapping.manage", "维护租户范围内的平台类目及商品属性映射。"),
    ("listings.task.view", "查看刊登任务与日志", "listings", "task.view", "查看刊登任务、步骤日志和异常。"),
    ("listings.task.manage", "管理刊登任务", "listings", "task.manage", "发起、重试或记录刊登执行任务；不代表已接通外部平台。"),
    ("listings.publish.production", "确认生产刊登", "listings", "publish.production", "二次确认生产模式的刊登任务。"),
)


def align_permissions(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    for code, name, module, action, description in PERMISSIONS:
        Permission.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "module": module,
                "action": action,
                "description": description,
            },
        )


class Migration(migrations.Migration):
    dependencies = [("permissions", "0025_expand_influencer_permissions")]
    operations = [migrations.RunPython(align_permissions, migrations.RunPython.noop)]
