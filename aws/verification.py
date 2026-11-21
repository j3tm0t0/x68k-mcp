"""Serve complete scoped annotation tables without semantic chunk truncation."""
import json
from pathlib import Path
from aws.calculator import calculate

TABLES = {f"{v['source_id']}:{v['pdf_page']}":v for path in (Path(__file__).resolve().parents[1]/'tables').glob('*.json') for v in [json.loads(path.read_text())]}

SOURCES = [json.loads(path.read_text()) for path in (Path(__file__).resolve().parents[1]/'sources').glob('*.json')]
for source in SOURCES:
    source['image_checked_table_pages']=sorted({entry['pdf_page'] for entry in TABLES.values() if entry['source_id']==source['id']})
    source['image_checked_table_catalog']=[{'pdf_page':entry['pdf_page'],'origin_label':entry['origin_label'],
      'tables':[{'id':table['id'],'title':table['title']} for table in entry['tables']]}
      for entry in sorted(TABLES.values(),key=lambda e:e['pdf_page']) if entry['source_id']==source['id']]


def cell(value,column):
    if value is None:return '未記載・該当なし'
    if type(value) is bool:return '対応あり' if value else '対応なし'
    if isinstance(value,list):return ' / '.join(cell(v,column) for v in value)
    return (str(value)+column.get('unit','')).replace('|','\\|').replace('\n',' ')


def read_tables(source_id,pdf_page):
    if not isinstance(source_id,str) or type(pdf_page) is not int or pdf_page<1:
        raise ValueError('source_id must be a string and pdf_page a positive integer')
    annotation=TABLES.get(f'{source_id}:{pdf_page}')
    if annotation is None:return {'source_id':source_id,'pdf_page':pdf_page,'tables':[],'notice':'No image-checked tables on this page. This does not mean no hardware feature exists.'}
    tables=[]
    for table in annotation['tables']:
        columns=table['columns']
        lines=['| '+' | '.join(c['label'] for c in columns)+' |','| '+' | '.join('---' for _ in columns)+' |']
        lines += ['| '+' | '.join(cell(row[c['key']],c) for c in columns)+' |' for row in table['rows']]
        tables.append({**table,'markdown':'\n'.join(lines)})
    return {**{k:v for k,v in annotation.items() if k!='tables'},'tables':tables,
            'instructions':'Complete annotation rows. Preserve separate conditions and false flags. Copy relevant markdown rows without regrouping conditions. AI image checks are not human review. Annotation scope is not the whole page.'}


def handler(event,context):
    custom=getattr(getattr(context,'client_context',None),'custom',None) or {}
    tool=custom.get('bedrockAgentCoreToolName')
    if not isinstance(event,dict):return {'error':'Arguments must be an object'}
    try:
        if tool=='verification___list_sources' and not event:return SOURCES
        if tool=='verification___calculate' and set(event)=={'expression'}:return calculate(event['expression'])
        if tool=='verification___read_tables' and set(event)=={'source_id','pdf_page'}:return read_tables(event['source_id'],event['pdf_page'])
        return {'error':'Unknown tool or unexpected arguments'}
    except (ValueError,SyntaxError,ZeroDivisionError,OverflowError):return {'error':'Invalid or out-of-bounds arguments'}
