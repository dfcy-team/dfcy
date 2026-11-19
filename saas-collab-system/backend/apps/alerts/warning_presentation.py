"""Shared snapshot presentation; summaries are computed once by the worker."""
FLAGS=('forecast_stockout','key_variant_shortage','supply_risk','excess_stock','new_product')
def summarize_spus(items):
    grouped={}
    for item in items:
        p=item['payload'];key=item['spu_id']
        if key is None:continue
        key=str(key);w=p.get('warning') or {}
        if key not in grouped:
            grouped[key]={'spu_id':item['spu_id'],'product_name':p.get('spu_name',p.get('product_name','')),'spu_code':p.get('spu_code',''),'legacy_spu_code':p.get('legacy_spu_code',''),'image_preview_url':p.get('image_preview_url',''),'sku_count':0,'warnings':[],'first_shortage_date':None,'shortage_sku_count':0,'confidence':'complete','incomplete_sku_count':0}
        g=grouped[key];g['sku_count']+=1
        g['incomplete_sku_count']+=w.get('state')=='unavailable'
        for f in FLAGS:
            if item[f] and f not in g['warnings']:g['warnings'].append(f)
        if w.get('confidence')=='reference':g['confidence']='reference'
        if not g['image_preview_url'] and p.get('image_preview_url'):g['image_preview_url']=p['image_preview_url']
        first=w.get('first_shortage_date')
        if first and (not g['first_shortage_date'] or first<g['first_shortage_date']):g['first_shortage_date']=first
        g['shortage_sku_count']+=bool(item['forecast_stockout'])
    return grouped
