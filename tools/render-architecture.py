#!/usr/bin/env python3
"""Generate separate runtime and UML repository views from one shared model."""
import argparse
from dataclasses import dataclass, field
import hashlib
import html
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zlib

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = {
    'gateway': 'HTTPS API, durable scheduling and result storage',
    'worker-portable': 'Node and PHP execution engines',
    'worker-android': 'Android service and execution engine',
    'worker-routeros': 'Container packaging and supervision of the PHP engine',
    'protocol': 'Wire contracts and examples; no running service',
    'platform': 'Deployment recipes and release bundles; no running service',
}

@dataclass
class Box:
    id: str
    title: str
    lines: tuple
    x: int
    y: int
    w: int
    h: int
    kind: str = 'component'
    owner: str = ''
    parent: str = ''

@dataclass
class Link:
    source: str
    target: str
    points: tuple
    label: tuple
    label_at: tuple
    kind: str = 'call'

@dataclass
class Diagram:
    title: str
    width: int
    height: int
    boxes: list = field(default_factory=list)
    links: list = field(default_factory=list)
    notes: list = field(default_factory=list)


def runtime():
    d = Diagram('How a task runs — runtime components', 1140, 800)
    d.boxes = [
        Box('canonical', 'Gateway and canonical stores', (), 350, 135, 455, 520, 'group'),
        Box('workers', 'Compatible execution hosts', (), 835, 130, 280, 410, 'group'),
        Box('application', 'External application', ('Creates tasks', 'Reads results and artifacts'), 25, 210, 235, 105, 'external'),
        Box('api', 'Gateway HTTPS API', ('Assigns attempts and leases', 'Accepts results / binary chunks', 'Authenticates each participant'), 425, 205, 245, 140, owner='gateway', parent='canonical'),
        Box('postgres', 'PostgreSQL', ('Jobs, attempts, receipts', 'Inbox / outbox metadata'), 385, 520, 205, 100, 'store', parent='canonical'),
        Box('artifacts', 'Artifact filesystem', ('Chunks and sealed files', 'Content hashes'), 610, 520, 185, 100, 'store', parent='canonical'),
        Box('broker', 'RabbitMQ — optional bridge', ('Command ingestion / event refs', 'Workers do not claim here'), 30, 520, 270, 100, 'external'),
        Box('node', 'Node worker', ('Linux / Windows',), 850, 175, 250, 48, owner='worker-portable', parent='workers'),
        Box('php', 'PHP CLI worker', ('Linux / shared hosting',), 850, 232, 250, 48, owner='worker-portable', parent='workers'),
        Box('android', 'Android service', ('Java / Rhino',), 850, 289, 250, 48, owner='worker-android', parent='workers'),
        Box('router', 'RouterOS container', (), 850, 348, 250, 117, 'group', 'worker-routeros', 'workers'),
        Box('router_php', 'PHP execution engine', ('Same portable SDK',), 864, 390, 222, 53, owner='worker-portable', parent='router'),
        Box('source', 'External HTTP source', ('Only for network tasks',), 850, 620, 250, 85, 'external'),
    ]
    d.links = [
        Link('application', 'api', ((260,268),(425,268)), ('1  Submit task','4  Read result'), (342,224)),
        Link('workers', 'api', ((835,268),(670,268)), ('2  Claim (reply: job)','3  Report / upload'), (753,224)),
        Link('api','postgres',((480,345),(480,520)),('SQL transactions',),(480,440)),
        Link('api','artifacts',((620,345),(705,345),(705,520)),('Binary chunks',),(705,440)),
        Link('api','broker',((425,310),(360,310),(360,470),(220,470),(220,520)),('Event refs / outbox',),(235,450),'optional'),
        Link('broker','api',((110,520),(110,385),(398,385),(398,292),(425,292)),('Commands / inbox',),(240,370),'optional'),
        Link('workers','source',((975,540),(975,620)),('GET / HEAD',),(1050,580)),
    ]
    d.notes = [
        (975, 492, ('Per-slot checkpoint + completion outbox', 'Local JSON state / SQLite'), 12),
        (570, 729, ('HTTPS arrows point from caller to service; replies use the same connection.',), 14),
        (570, 755, ('Dashed broker links: optional AMQP commands and event references.',), 13),
        (570, 784, ('Workers never connect directly to PostgreSQL or RabbitMQ.',), 15),
    ]
    return d


def repositories():
    d = Diagram('Where the repository fits — UML package dependencies',1080,710)
    d.boxes = [
        Box('implementations','Runtime code',(),35,260,1010,190,'group'),
        Box('protocol','protocol',('JSON Schemas / portable JS ABI','Contract, not a service'),410,100,260,115,'package','protocol'),
        Box('gateway','gateway',('API, leases, canonical results',),60,310,260,120,'package','gateway','implementations'),
        Box('worker-portable','worker-portable',('Node / PHP SDKs',),410,310,260,120,'package','worker-portable','implementations'),
        Box('worker-android','worker-android',('Android service / executor',),760,310,260,120,'package','worker-android','implementations'),
        Box('platform','platform',('Deployment recipes / release pins','Includes protocol version pin'),60,545,260,115,'package','platform'),
        Box('worker-routeros','worker-routeros',('ARM64 image / supervisor','Packages the PHP SDK locally'),760,545,260,115,'package','worker-routeros'),
    ]
    d.links = [
        Link('gateway','protocol',((190,310),(190,155),(410,155)),('conforms to contract',),(285,140),'dependency'),
        Link('worker-portable','protocol',((540,310),(540,215)),('contract',),(585,251),'dependency'),
        Link('worker-android','protocol',((890,310),(890,155),(670,155)),('conforms to contract',),(790,140),'dependency'),
        Link('platform','implementations',((190,545),(190,450)),('composes releases',),(275,500),'dependency'),
        Link('worker-routeros','worker-portable',((890,545),(890,490),(640,490),(640,430)),('packages PHP SDK',),(775,476),'dependency'),
    ]
    d.notes = [(540,692,('Dashed arrows point from user to supplier; they are not network connections.',),14)]
    return d


def scene(view):
    return runtime() if view == 'runtime' else repositories()


def model(component,view='runtime'):
    """Editable Graphviz source of the same semantic model used by the SVG."""
    d=scene(view); lines=['// Shared model: platform/tools/render-architecture.py', 'digraph Architecture {', 'graph [rankdir=TB, compound=true];', 'node [fontname="sans-serif"];']
    lines.append('label='+json.dumps(d.title+'\n'+component+': '+COMPONENTS[component])+';labelloc=t;')
    def name(identifier):return json.dumps(identifier)
    def emit(box,indent=''):
        selected=box.owner==component
        if box.kind=='group':
            lines.append(indent+'subgraph '+name('cluster_'+box.id)+' {')
            lines.append(indent+'label='+json.dumps(box.title)+'; style=dashed;')
            if selected:lines.append(indent+'color="#2058ad";penwidth=2.5;')
            lines.append(indent+name('anchor_'+box.id)+' [shape=point,width=0,style=invis];')
            for child in d.boxes:
                if child.parent==box.id:emit(child,indent+'  ')
            lines.append(indent+'}')
        else:
            shape={'package':'tab','store':'cylinder','external':'box'}.get(box.kind,'component')
            label='\n'.join([box.title,*box.lines]+(['THIS REPOSITORY']if selected and view=='repositories'else[]))
            attrs='shape='+shape+',label='+json.dumps(label)
            if selected:attrs+=',color="#2058ad",style=filled,fillcolor="#e8f0ff",penwidth=2.5'
            lines.append(indent+name(box.id)+' ['+attrs+'];')
    for box in d.boxes:
        if not box.parent:emit(box)
    by_id={b.id:b for b in d.boxes}
    for edge in d.links:
        attrs=['label='+json.dumps(' / '.join(edge.label))]
        if edge.kind in ['dependency','optional']:attrs+=['style=dashed']
        if edge.kind=='dependency':attrs+=['arrowhead=open']
        ids=[]
        for side,identifier in [('tail',edge.source),('head',edge.target)]:
            grouped=by_id[identifier].kind=='group';ids.append(name('anchor_'+identifier if grouped else identifier))
            if grouped:attrs.append('l'+side+'='+json.dumps('cluster_'+identifier))
        lines.append(' -> '.join(ids)+' ['+','.join(attrs)+'];')
    return '\n'.join(lines+['}'])+'\n'


def svg(component,view):
    d=scene(view);ns='http://www.w3.org/2000/svg';ET.register_namespace('',ns)
    root=ET.Element('{'+ns+'}svg',{'viewBox':f'0 0 {d.width} {d.height}','width':str(d.width),'height':str(d.height),'role':'img','aria-labelledby':'title description'})
    def el(parent,tag,**attrs):return ET.SubElement(parent,'{'+ns+'}'+tag,{k.replace('_','-'):str(v)for k,v in attrs.items()})
    el(root,'title',id='title').text=d.title+' — '+component
    el(root,'desc',id='description').text=COMPONENTS[component]
    el(root,'rect',x=0,y=0,width=d.width,height=d.height,fill='white')
    defs=el(root,'defs')
    for kind,path,fill in [('call','M0,-4 L8,0 L0,4 Z','#52657d'),('dependency','M0,-4 L8,0 L0,4','none')]:
        marker=el(defs,'marker',id=kind,viewBox='-1 -5 11 10',refX=8,refY=0,markerWidth=8,markerHeight=8,orient='auto')
        el(marker,'path',d=path,fill=fill,stroke='#52657d',stroke_width=1.3)
    def text(parent,x,y,parts,size=15,bold=False,color='#18314d',background=False):
        if background:
            w=max(map(len,parts))*size*.53+12
            el(parent,'rect',x=x-w/2,y=y-size+1,width=w,height=len(parts)*(size+5)+4,fill='white',opacity='.96')
        node=el(parent,'text',x=x,y=y,font_family='DejaVu Sans, sans-serif',font_size=size,text_anchor='middle',font_weight='bold'if bold else 'normal',fill=color)
        for i,value in enumerate(parts):el(node,'tspan',x=x,dy=0 if i==0 else size+5).text=value
    text(root,d.width/2,30,(d.title,),24,True)
    note=component+' — '+COMPONENTS[component]
    text(root,d.width/2,64,(note,),14,False,'#2058ad')
    # Frames first, then connections, then readable nodes/labels.
    for box in d.boxes:
        if box.kind!='group':continue
        owned=box.owner==component
        group=el(root,'g',id=box.id,data_owner=box.owner,data_owned=str(owned).lower())
        el(group,'rect',x=box.x,y=box.y,width=box.w,height=box.h,rx=5,fill='#f7faff',stroke='#2058ad'if owned else '#b4c0ce',stroke_width=2.5 if owned else 1.2,stroke_dasharray='none'if owned else '6 4')
        text(group,box.x+85 if box.id=='implementations' else box.x+box.w/2,box.y+23,(box.title,),14,True)
    for i,link in enumerate(d.links):
        attrs={'d':'M '+' L '.join(f'{x},{y}'for x,y in link.points),'fill':'none','stroke':'#52657d','stroke_width':1.7,'marker_end':'url(#'+('dependency'if link.kind=='dependency'else'call')+')','data_source':link.source,'data_target':link.target,'data_kind':link.kind}
        if link.kind in ['dependency','optional']:attrs['stroke_dasharray']='7 5'
        el(root,'path',**attrs)
    for box in d.boxes:
        if box.kind=='group':continue
        owned=box.owner==component
        group=el(root,'g',id=box.id,data_owner=box.owner,data_owned=str(owned).lower())
        bg='#e8f0ff'if owned else '#fffaf0'if box.kind=='external'else'#f2f5f9'
        border='#2058ad'if owned else'#8799ae'
        el(group,'rect',x=box.x,y=box.y,width=box.w,height=box.h,rx=3,fill=bg,stroke=border,stroke_width=2.5 if owned else 1.2)
        if box.kind=='component':
            for offset in [7,21]:el(group,'rect',x=box.x-5,y=box.y+offset,width=10,height=7,fill=bg,stroke=border)
        if box.kind=='package':
            el(group,'path',d=f'M {box.x},{box.y} v -12 h 75 l 10,12',fill=bg,stroke=border,stroke_width=1.2)
        if box.kind=='store':el(group,'ellipse',cx=box.x+box.w/2,cy=box.y+8,rx=box.w/2,ry=8,fill=bg,stroke=border)
        compact=box.h<65;title_y=box.y+(20 if compact else 34)
        text(group,box.x+box.w/2,title_y,(box.title,),15,True)
        if box.lines:text(group,box.x+box.w/2,title_y+(19 if compact else 27),box.lines,13 if compact else 14)
        if view=='repositories'and owned:text(group,box.x+box.w/2,box.y+box.h-11,('THIS REPOSITORY',),12,True,'#2058ad')
    for link in d.links:text(root,*link.label_at,link.label,12,background=True)
    for x,y,parts,size in d.notes:text(root,x,y,parts,size)
    return ET.tostring(root,encoding='utf-8',xml_declaration=True)+b'\n'


def render_png(source,destination,browser=None):
    from PIL import Image
    browser=browser or next((shutil.which(x)for x in ['chromium','chromium-browser','google-chrome']if shutil.which(x)),None)
    if not browser:raise RuntimeError('PNG rendering needs local Chromium; use --browser or render SVG only')
    tree=ET.fromstring(source.read_bytes());w,h=map(int,(tree.get('width'),tree.get('height')))
    with tempfile.TemporaryDirectory(prefix='fleet-uml-')as temporary:
        temporary=Path(temporary);page=temporary/'view.html'
        page.write_text(f'<!doctype html><meta charset="utf-8"><style>html,body{{margin:0;background:white;overflow:hidden}}img{{display:block;width:{w}px;height:{h}px}}</style><img src="'+html.escape(source.resolve().as_uri(),quote=True)+'">')
        out=subprocess.run([browser,'--headless','--disable-gpu','--no-sandbox','--no-first-run','--disable-background-networking','--hide-scrollbars','--force-device-scale-factor=1','--user-data-dir='+str(temporary/'profile'),'--screenshot='+str(destination.resolve()),f'--window-size={w},{h+180}',page.as_uri()],capture_output=True)
        if out.returncode:raise RuntimeError('Local diagram renderer failed')
        # Render at native SVG scale; discard only the extra browser canvas.
        with Image.open(destination)as image:image.crop((0,0,w,h)).save(destination)
    raw=destination.read_bytes();value=b'fleet-svg-sha256\x00'+hashlib.sha256(source.read_bytes()).hexdigest().encode();chunk=b'tEXt'+value
    chunk=struct.pack('>I',len(value))+chunk+struct.pack('>I',zlib.crc32(chunk)&0xffffffff)
    destination.write_bytes(raw[:33]+chunk+raw[33:])


def render(component,directory,png=False,browser=None):
    directory.mkdir(parents=True,exist_ok=True);hashes={}
    for view,stem in [('runtime','architecture'),('repositories','repositories')]:
        dot=model(component,view);(directory/(stem+'.dot')).write_text(dot)
        source=directory/(stem+'.svg');source.write_bytes(svg(component,view))
        if png:render_png(source,directory/(stem+'.png'),browser)
        hashes[view]=hashlib.sha256(source.read_bytes()).hexdigest()
    return hashes


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--component',choices=COMPONENTS,default='platform');parser.add_argument('--output',type=Path,default=ROOT/'docs')
    parser.add_argument('--workspace',type=Path);parser.add_argument('--png',action='store_true');parser.add_argument('--browser')
    args=parser.parse_args()
    names=list(COMPONENTS)if args.workspace else[args.component]
    for name in names:
        if args.workspace and not(args.workspace/'repos'/name/'README.md').is_file():parser.error('workspace lacks '+name)
    for name in names:
        destination=args.workspace/'repos'/name/'docs'if args.workspace else args.output
        print(name,json.dumps(render(name,destination,args.png,args.browser)),flush=True)

if __name__=='__main__':main()
