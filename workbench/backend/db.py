import os,json
from pathlib import Path
from datetime import datetime,timezone
from sqlalchemy import create_engine,String,Integer,DateTime,select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase,Mapped,mapped_column,sessionmaker
ROOT=Path(__file__).resolve().parents[1]
PRIVATE=ROOT/'data/private'
PRIVATE.mkdir(parents=True,exist_ok=True)
def now(): return datetime.now(timezone.utc).isoformat()
def db_url():
    if os.environ.get('DATABASE_URL'): return os.environ['DATABASE_URL']
    p=PRIVATE/'runtime.json'
    if p.exists(): return json.loads(p.read_text())['database_url']
    raise RuntimeError('本地 PostgreSQL 尚未初始化，请运行启动工作台.ps1')
class Base(DeclarativeBase):pass
class Record(Base):
    __tablename__='records'
    kind:Mapped[str]=mapped_column(String(30),primary_key=True)
    id:Mapped[str]=mapped_column(String(100),primary_key=True)
    revision:Mapped[int]=mapped_column(Integer,default=1)
    data:Mapped[dict]=mapped_column(JSONB)
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))
class Audit(Base):
    __tablename__='audit'
    id:Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True)
    at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))
    action:Mapped[str]=mapped_column(String(100))
    target:Mapped[str]=mapped_column(String(100))
    detail:Mapped[dict]=mapped_column(JSONB)
engine=create_engine(db_url(),pool_pre_ping=True,connect_args={'connect_timeout':5})
Session=sessionmaker(engine,expire_on_commit=False)
def read_all(s,kind):return s.scalars(select(Record).where(Record.kind==kind).order_by(Record.id)).all()
def put(s,kind,id,data):
    r=s.get(Record,(kind,id))
    if r:r.data=data;r.revision+=1;r.updated_at=datetime.now(timezone.utc)
    else:r=Record(kind=kind,id=id,data=data);s.add(r)
    return r
def audit(s,action,target,detail):s.add(Audit(action=action,target=target,detail=detail))
