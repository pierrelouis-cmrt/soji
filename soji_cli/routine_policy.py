"""Decode legacy routine fields and share initial/fresh item constraints."""


def normalize_routine(row):
    row=dict(row);conditions=dict(row.get('conditions') or {})
    for key in ('unusedForHours','minIdleHours','minItemBytes','freeBelowPercent','freeBelowBytes'):
        if key in row:conditions.setdefault(key,row[key])
    free=dict(conditions.get('freeBelow') or row.get('freeBelow') or {})
    for key in ('freeBelowPercent','freeBelowBytes'):
        value=conditions.get(key,free.get(key))
        if isinstance(value,dict):value=value.get('_0')
        if value is not None:free[key]={'_0':value}
    if free:conditions['freeBelow']=free
    row['conditions']=conditions
    if not row.get('groups') and row.get('target',{}).get('group'):row['groups']=[row['target']['group']]
    return row


def item_allowed(f,permit,now):
    return (f.tier=='regenerable' and f.comes_back in ('downloads','rebuilds')
            and (not permit.get('groups') or f.group in permit['groups'])
            and f.size>=permit.get('minItemBytes',0)
            and now-max(f.newest,f.last_activity or 0,f.date_added or 0)>=permit.get('minIdleHours',0)*3600)
