from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from app.config import ROOT, META
from app import store
from app.migration import service
from app.errors import BusinessError

router=APIRouter()
templates=Jinja2Templates(directory=str(ROOT/'app/templates'))


@router.get('/migration')
def page(request:Request):
    from app.main import DB_PATH
    migrations=store.list_migrations(DB_PATH)
    migration_id=request.query_params.get('migration_id')
    if migration_id:
        latest=store.get_migration(DB_PATH, migration_id)
    else:
        latest=store.get_migration(DB_PATH, migrations[0]['id']) if migrations else None
    return templates.TemplateResponse(request=request, name='migration.html',
                                      context={'meta':META, 'key':'migration', 'migrations':migrations, 'plan':latest})


@router.post('/api/migration/seed')
def seed():
    from app.main import DB_PATH
    return service.seed(DB_PATH)


@router.post('/api/migration/runs')
def migrate():
    from app.main import DB_PATH
    return service.run_migration(DB_PATH)


@router.get('/api/migration/runs')
def migrations():
    from app.main import DB_PATH
    return store.list_migrations(DB_PATH)


@router.get('/api/migration/runs/{migration_id}')
def migration(migration_id:str):
    from app.main import DB_PATH
    return store.get_migration(DB_PATH, migration_id)
