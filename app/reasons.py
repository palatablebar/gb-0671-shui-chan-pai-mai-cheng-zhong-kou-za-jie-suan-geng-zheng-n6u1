REASONS = {
    'COLUMN_COUNT':'列数错误', 'MISSING_ID':'编号缺失', 'DUPLICATE_CONFLICT':'重复编号冲突',
    'MISSING_VALUE':'数值缺失', 'BAD_NUMBER':'数值格式错误', 'BAD_TIME':'时间格式错误',
    'BAD_UNIT':'单位不受支持', 'UNKNOWN_REFERENCE':'引用对象不存在', 'INVALID_RANGE':'范围错误',
    'VERSION_CONFLICT':'版本冲突', 'EMPTY_FILE':'空文件', 'BLANK_FILE':'全空行',
    'HEADER_ONLY':'仅有表头', 'STALE_VERSION':'复核版本已更新', 'NOT_FOUND':'批次不存在',
    'MIG_SNAPSHOT_MISSING':'源快照缺失，不得替换现行版本',
    'MIG_INPUT_MISMATCH':'重算输入行数与封存证据无法对平',
    'MIG_QUARANTINE_MISMATCH':'重算隔离数与封存证据无法对平',
    'MIG_AMOUNT_MISMATCH':'重算金额与封存证据无法对平',
    'MIG_SEAL_MISMATCH':'封存指纹重算不一致，封存证据已被改写',
    'MIG_NEW_UNBALANCED':'新口径重算未通过守恒校验，不得切换',
}
def reject(state, record, code, detail):
    state['quarantine'].append({'line':record.get('_line',0),'id':record.get('id',''),
       'code':code,'detail':detail,'raw':{k:v for k,v in record.items() if not k.startswith('_')}})
