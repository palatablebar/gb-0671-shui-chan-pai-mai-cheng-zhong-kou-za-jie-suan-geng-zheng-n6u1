from pathlib import Path
import json, os
ROOT = Path(__file__).resolve().parents[1]
META = json.loads((ROOT / 'app/project.json').read_text())
MODULES = META['keys']
RULE_VERSION = '2026.11.17-r2'
# 扣杂规则升级：计价重量量化口径由 0.001kg 收紧到 0.01kg，金额仍四舍五入到分
RULE_VERSION_V2 = '2026.11.20-r3'
BILLABLE_QUANT = {RULE_VERSION: '.001', RULE_VERSION_V2: '.01'}
MIGRATION_WINDOW_DAYS = 90
DB_PATH = os.environ.get('DB_PATH', '/data/workbench.sqlite')
SENTINELS = {'', '-', 'N/A', 'NULL', '未知'}
MAX_BYTES = 2_000_000
