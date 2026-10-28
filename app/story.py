"""Free-form characters and chronological actions/dialogue within a 15-second film."""
import math
import re


class StoryError(ValueError):
    pass


def characters(values):
    if not isinstance(values,list) or len(values)>20: raise StoryError("角色列表格式不正确，请精简到20个角色以内。")
    result=[]
    for i,item in enumerate(values):
        if isinstance(item,str):
            item={"id":chr(65+i),"name":chr(65+i),"description":item}
        if not isinstance(item,dict): raise StoryError("角色信息格式不正确。")
        name=str(item.get("name","")).strip()
        if not name:continue
        role={"id":str(item.get("id",f"C{i+1}")),"name":name,"description":str(item.get("description","")).strip()}
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,24}",role["id"]) or not 1<=len(name)<=20 or len(role["description"])>120 or re.search(r"[:：\n\r]",name):
            raise StoryError("角色名最多20字，描述最多120字，名字不要包含冒号或换行。")
        if any(r["id"]==role["id"] or r["name"]==name for r in result):raise StoryError("角色名或编号重复，请使用不同名字。")
        result.append(role)
    return result


def parse_script(script,roles,discover=False):
    if not isinstance(script,str) or len(script)>2000:raise StoryError("每段剧情脚本最多2000字。")
    events=[]
    for line in filter(None,(line.strip() for line in script.splitlines())):
        pair=re.match(r"^([^:：\n]{1,60})[:：]\s*(.*)$",line)
        if pair and pair[1].strip() not in {"动作","场景","画面","环境","镜头"}:
            prefix,text=pair[1].strip(),pair[2].strip().strip('“”"')
            role=next((r for r in roles if prefix==r["name"] or prefix.startswith(r["name"]+"（") or prefix.startswith(r["name"]+"(")),None)
            if role is None and discover:
                name=re.split(r"[（(]",prefix)[0].strip()
                if len(name)>20:raise StoryError("请将台词写成“角色名：台词”，动作单独一行。")
                role={"id":f"C{len(roles)+1}","name":name,"description":""}
                while any(r["id"]==role["id"] for r in roles):role["id"]="R"+role["id"]
                roles.append(role)
            if role is None:raise StoryError(f"未找到角色“{prefix}”，请添加角色，或将该行写为“动作：…”。")
            if not text:continue
            delivery=prefix[len(role["name"]):].strip("（）() ")
            events.append({"kind":"dialogue","speaker":role["id"],"speaker_name":role["name"],"text":text,"delivery":delivery})
        else:
            action=pair[2] if pair else line
            if action.strip():events.append({"kind":"action","text":action.strip()})
    return events


def speech_seconds(text):
    # A conservative planning estimate, not a claim about generated speech timing.
    chinese=len(re.findall(r"[\u3400-\u9fff]",text))
    words=len(re.findall(r"[A-Za-z0-9]+(?:'[A-Za-z]+)?",text))
    pauses=len(re.findall(r"[，。！？,.!?；;]",text))
    return chinese/3.6+words/2.2+pauses*.12


def timing(plan):
    issues=[];warnings=[];total=0.;estimates=[];all_roles=set()
    for i,shot in enumerate(plan["shots"],1):
        seconds=shot["duration"];total+=seconds
        turns=shot.get("turns",[])
        spoken=sum(speech_seconds(t["text"])+.18 for t in turns)
        if plan.get("audio_mode")=="narration":spoken=speech_seconds(shot.get("narration",""))
        action=shot.get("action_seconds",0)
        need=spoken+action+.5
        estimates.append({"shot":i,"allocated":seconds,"speech":round(spoken,1),"action_minimum":action,"estimated_minimum":round(need,1)})
        if need>seconds+.01:issues.append(f"镜头{i}预计至少需要{need:.1f}秒，目前分配{seconds:g}秒；请缩短台词、减少动作或重新分配时长。")
        all_roles.update(t["speaker"] for t in turns)
        if len(shot.get("events",[]))>8:warnings.append(f"镜头{i}事件较多，建议集中在一个目标和一个结果。")
    if abs(total-15)>.01:issues.append(f"目前总时长{total:g}秒，请调整为15秒。")
    if len(all_roles)>3:warnings.append("说话角色较多，15秒内可能增加声音混淆风险；请检查每句说话人。")
    return {"ready":not issues,"total_seconds":round(total,2),"shots":estimates,"issues":issues,"warnings":warnings,
            "role_count":len(plan.get("characters",[])),"dialogue_turn_count":sum(len(s.get("turns",[])) for s in plan["shots"]),
            "action_count":sum(sum(e["kind"]=="action" for e in s.get("events",[])) for s in plan["shots"]),
            "note":"估算按正常语速计算；动作最少时长由你确认。不会自动截断、改写或删掉剧情。生成后仍需核对表演与台词。"}


def build(brief,style,ratio,role_values,script):
    roles=characters(role_values)
    sections=[];current=None;preamble=[]
    for line in (script or "").splitlines():
        header=re.match(r"^\s*(\d+)\s*[-—–~至]\s*(\d+)\s*秒?\s*[|｜:：]?\s*(.*)$",line)
        if header:
            start,end=int(header[1]),int(header[2])
            if start!=(sections[-1]["end"] if sections else 0) or end<=start:
                raise StoryError("时间段需从0秒开始、连续衔接且不重叠，例如0-4秒、4-10秒、10-15秒。")
            current={"start":start,"end":end,"lines":[header[3]] if header[3].strip() else []};sections.append(current)
        elif current is not None:current["lines"].append(line)
        elif line.strip():
            preamble.append(line)
    if sections and preamble:raise StoryError("已使用分段时间，请把每行剧情放到对应时间段下面，避免遗漏。")
    if not sections:sections=[{"start":0,"end":15,"lines":(script or "").splitlines()}]
    elif sections[-1]["end"]!=15:raise StoryError("最后一个时间段请结束在15秒。")
    if len(sections)>6:raise StoryError("当前接口最多支持6个镜头，请合并相邻时间段。")
    shots=[]
    for i,section in enumerate(sections,1):
        text="\n".join(section["lines"]).strip()
        events=parse_script(text,roles,discover=True)
        shots.append({"index":i,"name":f"剧情段落{i}","duration":section["end"]-section["start"],
                      "visual":brief,"narration":"","script":text,"events":events,
                      "turns":[e for e in events if e["kind"]=="dialogue"],"action_seconds":max(2,sum(e["kind"]=="action" for e in events)*1.5) if any(e["kind"]=="action" for e in events) or not events else 0,
                      "speaker":"","dialogue":""})
    roles=characters(roles)
    result={"title":re.split(r"[，。！？\n]",brief)[0][:12] or "我的剧情短片","brief":brief,"style":style,"ratio":ratio,
            "audio_mode":"dialogue","characters":roles,"shots":shots,"planner":"script","planner_label":"自由剧情 · 保留你的动作与台词"}
    result["timing"]=timing(result)
    return result


def normalize(value,strict=True):
    shots=value.get("shots")
    if not isinstance(shots,list) or not 1<=len(shots)<=6:raise StoryError("请保留1至6个镜头，总时长15秒。")
    roles=characters(value.get("characters",[]))
    mode=value.get("audio_mode","narration")
    if mode not in {"narration","dialogue","silent"}:raise StoryError("人声方式不正确。")
    title=str(value.get("title","我的短片")).strip()
    if not 1<=len(title)<=40:raise StoryError("标题应为1至40字。")
    result={"title":title,"characters":roles,"audio_mode":mode,"shots":[]}
    ids={r["id"]:r["name"] for r in roles}
    for i,shot in enumerate(shots,1):
        if not isinstance(shot,dict):raise StoryError("镜头格式不正确。")
        seconds=shot.get("duration",5)
        if isinstance(seconds,bool) or not isinstance(seconds,(int,float)) or not math.isfinite(seconds) or seconds!=int(seconds) or not 1<=seconds<=15:raise StoryError("每个镜头时长需为1至15秒的整数。")
        visual=str(shot.get("visual","")).strip()
        narration=str(shot.get("narration","")).strip() if mode=="narration" else ""
        if not 4<=len(visual)<=1200 or len(narration)>150:raise StoryError(f"镜头{i}画面描述需4至1200字，旁白最多150字。")
        script=shot.get("script")
        if script is not None:
            events=parse_script(script,roles,discover=not strict) if mode=="dialogue" else []
        elif shot.get("turns") is not None:
            events=[]
            if not isinstance(shot["turns"],list) or len(shot["turns"])>60 or any(not isinstance(t,dict) for t in shot["turns"]):raise StoryError("台词列表格式不正确。")
            for turn in shot["turns"]:
                who=str(turn.get("speaker",""));text=str(turn.get("text","")).strip()
                if who not in ids or len(text)>500:raise StoryError(f"镜头{i}台词角色不正确或内容过长。")
                if text:events.append({"kind":"dialogue","speaker":who,"speaker_name":ids[who],"text":text,"delivery":str(turn.get("delivery",""))[:80]})
            script="\n".join(f"{e['speaker_name']}：{e['text']}" for e in events)
        elif shot.get("dialogue"):
            who=str(shot.get("speaker",""))
            if who not in ids:raise StoryError(f"镜头{i}请指定已有角色。")
            events=[{"kind":"dialogue","speaker":who,"speaker_name":ids[who],"text":str(shot["dialogue"]),"delivery":""}]
            script=f"{ids[who]}：{shot['dialogue']}"
        else:events=[];script=""
        action=shot.get("action_seconds",0)
        if isinstance(action,bool) or not isinstance(action,(int,float)) or not math.isfinite(action) or not 0<=action<=60:raise StoryError("动作最少时长需为0至60秒。")
        turns=[e for e in events if e["kind"]=="dialogue"]
        result["shots"].append({"index":i,"name":str(shot.get("name",f"镜头{i}"))[:24],"duration":int(seconds),"visual":visual,"narration":narration,"script":script,
            "events":events,"turns":turns,"action_seconds":action,"speaker":turns[0]["speaker"] if len(turns)==1 else "","dialogue":turns[0]["text"] if len(turns)==1 else ""})
    result["characters"]=characters(roles)
    result["timing"]=timing(result)
    if strict and not result["timing"]["ready"]:raise StoryError("；".join(result["timing"]["issues"]))
    return result
