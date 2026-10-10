import os, sqlite3, secrets, json, asyncio
from pathlib import Path
from datetime import datetime, timezone
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')
DB = ROOT / 'council.db'
app = FastAPI(title='AI Council')
app.mount('/static', StaticFiles(directory=ROOT/'static'), name='static')

def db():
    conn=sqlite3.connect(DB)
    conn.row_factory=sqlite3.Row
    return conn

def init():
    with db() as c:
        c.execute('CREATE TABLE IF NOT EXISTS projects (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, question TEXT NOT NULL, stage INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT "new", created_at TEXT NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS responses (id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL, stage INTEGER NOT NULL, agent TEXT NOT NULL, content TEXT NOT NULL, FOREIGN KEY(project_id) REFERENCES projects(id))')
        c.execute('CREATE TABLE IF NOT EXISTS decisions (id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL, stage INTEGER NOT NULL, decision TEXT NOT NULL, created_at TEXT NOT NULL)')
init()

def auth(x_council_password: str | None = Header(default=None)):
    password=os.getenv('COUNCIL_PASSWORD','')
    if not password or password == 'change-this-password':
        raise HTTPException(503,'Set a secure COUNCIL_PASSWORD in .env first')
    if not x_council_password or not secrets.compare_digest(x_council_password,password):
        raise HTTPException(401,'Incorrect password')

class ProjectIn(BaseModel):
    title: str = Field(min_length=1,max_length=120)
    question: str = Field(min_length=3,max_length=12000)

@app.get('/')
def home(): return FileResponse(ROOT/'static'/'index.html')

@app.get('/api/projects', dependencies=[Depends(auth)])
def projects():
    with db() as c:
        return [dict(r) for r in c.execute('SELECT * FROM projects ORDER BY id DESC')]

@app.post('/api/projects', dependencies=[Depends(auth)])
def create(payload: ProjectIn):
    with db() as c:
        cur=c.execute('INSERT INTO projects(title,question,created_at) VALUES(?,?,?)',(payload.title,payload.question,datetime.now(timezone.utc).isoformat()))
        return {'id':cur.lastrowid}

@app.get('/api/projects/{pid}', dependencies=[Depends(auth)])
def detail(pid:int):
    with db() as c:
        p=c.execute('SELECT * FROM projects WHERE id=?',(pid,)).fetchone()
        if not p: raise HTTPException(404,'Project not found')
        r=[dict(x) for x in c.execute('SELECT stage,agent,content FROM responses WHERE project_id=? ORDER BY id',(pid,))]
        d=[dict(x) for x in c.execute('SELECT stage,decision,created_at FROM decisions WHERE project_id=? ORDER BY id',(pid,))]
        return {'project':dict(p),'responses':r,'decisions':d}

AGENTS=['ChatGPT','Claude','Gemini']
async def ask(agent, prompt):
    if os.getenv('DEMO_MODE','true').lower()=='true':
        return f'[DEMO — gerçek AI yanıtı değil] {agent}: Bu konuyu değerlendirmek için gereksinimleri, bütçeyi, riskleri ve doğrulanması gereken varsayımları ayrı ayrı ele almalıyız.'
    async with httpx.AsyncClient(timeout=75) as client:
        if agent=='ChatGPT':
            key=os.getenv('OPENAI_API_KEY')
            if not key: raise ValueError('OPENAI_API_KEY missing')
            r=await client.post('https://api.openai.com/v1/chat/completions',headers={'Authorization':f'Bearer {key}'},json={'model':os.getenv('OPENAI_MODEL','gpt-4.1-mini'),'messages':[{'role':'user','content':prompt}],'max_tokens':1100})
            r.raise_for_status(); return r.json()['choices'][0]['message']['content']
        if agent=='Claude':
            key=os.getenv('ANTHROPIC_API_KEY')
            if not key: raise ValueError('ANTHROPIC_API_KEY missing')
            r=await client.post('https://api.anthropic.com/v1/messages',headers={'x-api-key':key,'anthropic-version':'2023-06-01'},json={'model':os.getenv('ANTHROPIC_MODEL','claude-sonnet-4-5'),'max_tokens':1100,'messages':[{'role':'user','content':prompt}]})
            r.raise_for_status(); return '\n'.join(x['text'] for x in r.json()['content'] if x['type']=='text')
        key=os.getenv('GEMINI_API_KEY')
        if not key: raise ValueError('GEMINI_API_KEY missing')
        model=os.getenv('GEMINI_MODEL','gemini-2.5-flash')
        r=await client.post(f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',headers={'x-goog-api-key':key},json={'contents':[{'parts':[{'text':prompt}]}],'generationConfig':{'maxOutputTokens':1100}})
        r.raise_for_status(); return '\n'.join(p.get('text','') for c in r.json().get('candidates',[]) for p in c.get('content',{}).get('parts',[]))

@app.post('/api/projects/{pid}/run', dependencies=[Depends(auth)])
async def run(pid:int):
    with db() as c:
        p=c.execute('SELECT * FROM projects WHERE id=?',(pid,)).fetchone()
        if not p: raise HTTPException(404,'Project not found')
        if p['status'] not in ('new','approved'): raise HTTPException(409,'Awaiting your decision or already complete')
        if p['stage']>=3: raise HTTPException(409,'Maximum three rounds reached')
        stage=p['stage']+1
        previous=[dict(x) for x in c.execute('SELECT stage,agent,content FROM responses WHERE project_id=? ORDER BY id',(pid,))]
        c.execute('UPDATE projects SET status="running" WHERE id=?',(pid,))
    context='\n'.join(f"ROUND {x['stage']} {x['agent']}: {x['content'][:3500]}" for x in previous)
    if stage==1:
        prompt=f"Answer independently in Turkish. Be concrete, mention assumptions and risks. Project: {p['question']}"
    else:
        prompt=f"Project: {p['question']}\nOther AI responses:\n{context}\nReview others critically, identify errors, disagreements, and propose improvements. Respond in Turkish. Do not assume consensus."
    results=await asyncio.gather(*(ask(a,prompt) for a in AGENTS),return_exceptions=True)
    with db() as c:
        for agent,result in zip(AGENTS,results):
            content=f'ERROR: {type(result).__name__}: {str(result)[:250]}' if isinstance(result,Exception) else result
            c.execute('INSERT INTO responses(project_id,stage,agent,content) VALUES(?,?,?,?)',(pid,stage,agent,content))
        c.execute('UPDATE projects SET stage=?, status="review" WHERE id=?',(stage,pid))
    return {'stage':stage,'status':'review'}

class DecisionIn(BaseModel):
    decision: str

@app.post('/api/projects/{pid}/decision', dependencies=[Depends(auth)])
def decide(pid:int, payload:DecisionIn):
    if payload.decision not in ('approve','stop'): raise HTTPException(400,'Choose approve or stop')
    with db() as c:
        p=c.execute('SELECT * FROM projects WHERE id=?',(pid,)).fetchone()
        if not p: raise HTTPException(404,'Project not found')
        if p['status']!='review': raise HTTPException(409,'No pending review')
        status='approved' if payload.decision=='approve' and p['stage']<3 else 'complete'
        c.execute('INSERT INTO decisions(project_id,stage,decision,created_at) VALUES(?,?,?,?)',(pid,p['stage'],payload.decision,datetime.now(timezone.utc).isoformat()))
        c.execute('UPDATE projects SET status=? WHERE id=?',(status,pid))
    return {'status':status}
