"""Roll up explicit saved native-MCP runs; no network or model calls."""
import argparse
import json
from pathlib import Path
from x68k_knowledge.mcp_evaluation import case_question,has_evidence,DIMENSIONS,answer_hard_errors

ROOT=Path(__file__).resolve().parents[1]


def summarize(paths,rubric):
    history={};latest={}
    reports=sorted([(json.loads(path.read_text()),path) for path in paths],key=lambda item:item[0]['created_at'])
    for report,path in reports:
        if report['rubric_version']!=rubric['version']:raise ValueError('Different rubric version: '+str(path))
        for record in report['records']:
            case=record['case']
            if record['question']!=case_question(case,rubric['cases'][case]):raise ValueError('Different question: '+case)
            if record['answer_model']!='gpt-5.4-mini' or record.get('answer_effort') not in {'medium','high'}:raise ValueError('Different answer configuration: '+str(path))
            history.setdefault(case,[]).append((record,path));latest[case]=(record,path)
    satisfied={}
    for case,(record,_) in latest.items():
        satisfied[case]=(record['status']=='pass' and record['grade']['satisfaction']==4
          and record.get('hard_check_version',0)>=2 and not answer_hard_errors(case,record.get('answer',''))
          and any(t['name']=='retrieve_reference' and has_evidence(t) for t in record.get('trace',[])))
    missing=sorted(set(rubric['cases'])-latest.keys())
    lines=['# AWSネイティブMCPの実回答・採点', '',f"採点基準: {rubric['version']}",
      f"カタログ {len(rubric['cases'])}問 / 最新回答の確認 {len(latest)}問 / 満足度4かつ合格 {sum(satisfied.values())}問",'',
      '回答モデルはGPT-5.4 mini（medium/high、下表に明記）、採点モデルはGPT-5.4。実MCPの取得履歴を伴う記録。',
      '表は各問の最新結果。以前の失敗も各問の履歴に残す。全体の統計的な正答率を表すものではない。','',
      '|ケース|思考量|最新判定|正確さ/根拠/網羅性/実用性/満足度|履歴|','|---|---|---|---|---|']
    for case in rubric['cases']:
        if case not in latest:
            lines.append(f'|{case}|—|未確認|—|—|');continue
        record,path=latest[case];grade=record.get('grade') or {}
        scores='/'.join(str(grade.get(d,'—')) for d in DIMENSIONS)
        states=' → '.join(r['status'] for r,_ in history[case])
        lines.append(f"|{case}|{record['answer_effort']}|{record['status']}{'' if satisfied[case] else '（要確認）'}|{scores}|{states}|")
    if missing:lines+=['','未確認: '+', '.join(missing)]
    lines+=['','実行ごとに質問開始60秒以上、MCP操作10秒以上の間隔。ツールは1問6回まで。',
      '生の取得本文を含むJSONは同じGit対象外ディレクトリに保存。ここには実回答と採点理由を掲載する。','']
    for case in rubric['cases']:
        if case not in latest:continue
        record,path=latest[case]
        lines += [f'## {case}', '',record['question'],'',record.get('answer','回答未完了'),'',
          '### 判定・履歴','',f"最新: {record['status']} / {path.name}", '']
        grade=record.get('grade')
        if grade:
            lines+=[grade['reason'],'']
            for key in ('critical_errors','unsupported_claims','missing_facts'):
                lines += ['- '+key+': '+v for v in grade[key]]
        for error in record.get('hard_errors',[]):lines.append('- 固定チェック: '+error)
        if len(history[case])>1:
            lines += ['', '過去の結果: '+', '.join(f'{p.name}: {r["status"]}' for r,p in history[case][:-1])]
        lines += ['', '実ツール:', *[f"- {t.get('mcp_tool_name',t['name'])}: {json.dumps(t['arguments'],ensure_ascii=False)}" for t in record.get('trace',[])], '']
    return '\n'.join(lines),not missing and all(satisfied.values())


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('reports',type=Path,nargs='+')
    parser.add_argument('--rubrics',type=Path,default=ROOT/'evals/rubrics.json')
    parser.add_argument('--output',type=Path,default=ROOT/'tmp/mcp-evaluation/native-quality-summary.md')
    args=parser.parse_args();text,complete=summarize(args.reports,json.loads(args.rubrics.read_text()))
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(text)
    print(json.dumps({'output':str(args.output),'all_cases_satisfied':complete}))
