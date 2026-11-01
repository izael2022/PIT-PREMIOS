import json, logging, time, threading, urllib.parse, urllib.request, urllib.error
from html import escape
import database as db
from config import BOT_TOKEN, ADMIN_IDS, POINTS_PER_REFERRAL, DAILY_REWARD, MIN_REDEEM_POINTS

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
log=logging.getLogger("pit_premios")
API=f"https://api.telegram.org/bot{BOT_TOKEN}/"
BOT_USERNAME=""
PENDING_TASK_PROOFS={}
BANNER_URL="https://raw.githubusercontent.com/izael2022/PIT-PREMIOS/main/assets/pit_premios_banner.jpg"

def api(method, data=None):
    payload=urllib.parse.urlencode({k: json.dumps(v, ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in (data or {}).items()}).encode()
    req=urllib.request.Request(API+method, data=payload)
    try:
        with urllib.request.urlopen(req, timeout=40) as r: result=json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Telegram HTTP {e.code}: {e.read().decode('utf-8','replace')[:250]}")
    if not result.get("ok"): raise RuntimeError(str(result))
    return result.get("result")

def send(chat, text, keyboard=None):
    d={"chat_id":chat,"text":text,"parse_mode":"HTML"}
    if keyboard: d["reply_markup"]={"inline_keyboard":keyboard}
    return api("sendMessage",d)

def notify_user(uid,message):
    try:
        if db.notifications_enabled(uid):
            send(uid,message)
    except Exception:
        log.exception("Falha ao enviar notificação ao usuário %s",uid)

BANNER_BYTES=None

def send_photo(chat,photo,caption,keyboard=None):
    global BANNER_BYTES
    try:
        if BANNER_BYTES is None:
            urls=[photo,"https://cdn.jsdelivr.net/gh/izael2022/PIT-PREMIOS@main/assets/pit_premios_banner.jpg"]
            last_error=None
            for image_url in urls:
                try:
                    req=urllib.request.Request(image_url,headers={"User-Agent":"Mozilla/5.0"})
                    with urllib.request.urlopen(req,timeout=20) as response:
                        image_data=response.read()
                    if not (image_data.startswith(bytes([255,216])) or image_data.startswith(bytes([137,80,78,71]))):
                        raise ValueError("O endereço não retornou uma imagem JPG/PNG válida.")
                    BANNER_BYTES=image_data
                    break
                except Exception as download_error:
                    last_error=download_error
                    log.warning("Falha ao baixar banner de %s: %s",image_url,download_error)
            if BANNER_BYTES is None:
                raise RuntimeError(f"Não foi possível obter o banner: {last_error}")
        boundary="----PITPREMIOSBoundary7MA4YWxk"
        fields={"chat_id":str(chat),"caption":caption,"parse_mode":"HTML"}
        if keyboard:
            fields["reply_markup"]=json.dumps({"inline_keyboard":keyboard},ensure_ascii=False)
        body=bytearray()
        crlf=b"\r\n"
        for name,value in fields.items():
            body.extend(("--"+boundary).encode("ascii")+crlf)
            body.extend(('Content-Disposition: form-data; name="'+name+'"').encode("utf-8")+crlf+crlf)
            body.extend(str(value).encode("utf-8")+crlf)
        body.extend(("--"+boundary).encode("ascii")+crlf)
        body.extend(b'Content-Disposition: form-data; name="photo"; filename="pit_premios_banner.jpg"'+crlf)
        body.extend(b"Content-Type: image/jpeg"+crlf+crlf)
        body.extend(BANNER_BYTES+crlf)
        body.extend(("--"+boundary+"--").encode("ascii")+crlf)
        req=urllib.request.Request(API+"sendPhoto",data=bytes(body),headers={"Content-Type":"multipart/form-data; boundary="+boundary})
        try:
            with urllib.request.urlopen(req,timeout=40) as response:
                result=json.loads(response.read())
        except urllib.error.HTTPError as e:
            detail=e.read().decode("utf-8","replace")[:1000]
            raise RuntimeError(f"Telegram sendPhoto HTTP {e.code}: {detail}") from e
        if not result.get("ok"):
            raise RuntimeError(str(result))
        return result.get("result")
    except Exception:
        log.exception("Não foi possível enviar o banner; enviando boas-vindas em texto.")
        fallback="🐾 <b>PIT PRÊMIOS</b>\n\n"+caption
        return send(chat,fallback,keyboard)

def admin(uid): return uid in ADMIN_IDS
def btn(label,data): return {"text":label,"callback_data":data}
def menu():
    return [[btn("👤 Meu perfil","profile"),btn("💰 Carteira","wallet")],
            [btn("🎯 Missões","missions"),btn("🎁 Check-in","daily")],
            [btn("🚀 Convidar","invite"),btn("🏆 Ranking","ranking")],
            [btn("💎 Clube VIP","vip"),btn("🎟️ Resgatar","redeem_info")],
            [btn("🎁 Loja de prêmios","shop")],
            [btn("📜 Extrato","history"),btn("🔔 Notificações","notifications")],
            [btn("❓ Ajuda","help")],
            [btn("📋 Tarefas disponíveis","tasks")]]
def back(): return [[btn("⬅️ Menu principal","home")]]

def admin_menu():
    return [[btn("📊 Estatísticas","admin:stats"),btn("👤 Consultar usuário","admin:user")],
            [btn("➕ Adicionar pontos","admin:add"),btn("💎 Gerenciar VIP","admin:vip")],
            [btn("🎟️ Resgates","admin:orders"),btn("💸 Saques Pix","admin:payouts")],
            [btn("🎁 Pedidos da loja","admin:rewardorders")],
            [btn("🛡️ Análise antifraude","admin:fraud")],
            [btn("📋 Revisar tarefas","admin:tasks"),btn("🗂️ Gerenciar tarefas","admin:manage_tasks")],
            [btn("📢 Enviar comunicado","admin:broadcast")],
            [btn("⬅️ Fechar painel","home")]]

def start(m):
    u=m.get("from",{}); chat=m["chat"]["id"]; p=(m.get("text") or "").split(maxsplit=1)
    ref=int(p[1]) if len(p)>1 and p[1].isdigit() else None
    created,refid,review_id=db.register_user(u["id"],u.get("username"),u.get("first_name") or "",ref,POINTS_PER_REFERRAL,bool(u.get("is_bot")))
    if created and refid and POINTS_PER_REFERRAL:
        if review_id:
            try:
                notify_user(refid,"🛡️ Sua nova indicação entrou em análise de segurança. Os pontos serão liberados após a revisão.")
                for aid in ADMIN_IDS:
                    send(aid,f"🛡️ <b>INDICAÇÃO EM ANÁLISE #{review_id}</b>\nIndicador: <code>{refid}</code>\nNovo usuário: <code>{u['id']}</code>\nMotivo: conta de bot ou volume elevado de cadastros.",[[btn("Ver análise","admin:fraud")]])
            except Exception: log.exception("Falha ao notificar análise antifraude")
        else:
            try: notify_user(refid,f"🎉 Você ganhou {POINTS_PER_REFERRAL} pontos por uma indicação!")
            except Exception: log.exception("Falha ao notificar indicador")
    global BOT_USERNAME
    pr=db.get_profile(u["id"])
    first=escape((u.get("first_name") or "participante")[:40])
    send_photo(chat,BANNER_URL,f"🐾 <b>Olá, {first}!</b> Bem-vindo ao PIT PRÊMIOS.\n\n💰 Carteira: <b>{pr['points']:,} pontos</b>\n👥 Convites: <b>{pr['referrals']}</b>\n🔥 Sequência: <b>{pr['daily_streak']} dias</b>\n\n<i>Seus pontos. Suas conquistas. Seus prêmios.</i>",menu())

def balance(chat,uid):
    u=db.get_user(uid); points=u["points"] if u else 0
    send(chat,f"💰 <b>SUA CARTEIRA</b>\n━━━━━━━━━━━━━━━━━━\nSaldo: <b>{points:,} pontos</b>\nValor equivalente: <b>R$ {points/100:.2f}</b>\n\n📌 Conversão: 100 pontos = R$ 1,00\n💸 Saque mínimo: 1.000 pontos (R$ 10,00)\n\nPara solicitar: <code>/sacar PONTOS TIPO_CHAVE CHAVE_PIX</code>\nExemplo: <code>/sacar 1000 CPF 12345678900</code>\nTipos: CPF, CNPJ, EMAIL, TELEFONE ou ALEATORIA.",back())

def ranking(chat):
    lines=["🏆 <b>TOP 10 PIT PRÊMIOS</b>"]
    for i,u in enumerate(db.ranking(),1):
        name=u["first_name"] or ("@"+u["username"] if u["username"] else str(u["user_id"]))
        lines.append(f"{i}. {escape(name)} — {u['points']} pts")
    send(chat,"\n".join(lines))


def ranking_menu(chat):
    send(chat,"🏆 <b>RANKING PIT PRÊMIOS</b>\\n\\nEscolha qual classificação deseja consultar:",[[btn("📅 Ranking semanal — últimos 7 dias","ranking:weekly")],[btn("🏆 Ranking geral — pontos acumulados","ranking:general")],[btn("⬅️ Menu principal","home")]])

def weekly_ranking(chat):
    lines=["📅 <b>TOP 10 DA SEMANA</b>","<i>Pontos ganhos nos últimos 7 dias.</i>","━━━━━━━━━━━━━━━━━━"]
    rows=db.weekly_ranking()
    if not rows:
        lines.append("Ainda não há pontos registrados nesta semana. Participe das missões e atividades!")
    for i,u in enumerate(rows,1):
        name=u["first_name"] or ("@"+u["username"] if u["username"] else str(u["user_id"]))
        lines.append(f"{i}. {escape(name)} — <b>{u['points']} pts</b>")
    send(chat,"\\n".join(lines),[[btn("🏆 Ver ranking geral","ranking:general")],[btn("⬅️ Voltar","ranking")]])

def daily(chat,uid):
    ok,streak,earned=db.daily_claim(uid,DAILY_REWARD)
    if ok:
        day=(streak-1)%7+1
        next_day=day%7+1
        send(chat,f"🎉 <b>CHECK-IN CONFIRMADO!</b>\nVocê recebeu <b>+{earned} pontos</b>!\n🔥 Sequência atual: <b>{streak} dias</b>\n📅 Dia da recompensa: <b>{day}/7</b>\n\n<i>Volte amanhã para ganhar a recompensa do dia {next_day}!</i>",back())
    else:
        send(chat,f"⏳ <b>Check-in já realizado!</b>\nSua sequência atual é de <b>{streak} dias</b>. Volte amanhã.",back())

def profile(chat,uid):
    p=db.get_profile(uid); u=db.get_user(uid)
    name=escape((u["first_name"] or "Participante")[:40]); vip="ATIVO 💎" if u and u["is_vip"] else "COMUM"
    send(chat,f"👤 <b>SEU PERFIL PIT</b>\n━━━━━━━━━━━━━━━━━━\nOlá, <b>{name}</b>\n🆔 ID: <code>{uid}</code>\n💰 Saldo: <b>{p['points']:,} pontos</b>\n👥 Amigos convidados: <b>{p['referrals']}</b>\n🔥 Sequência diária: <b>{p['daily_streak']} dias</b>\n💎 Categoria: <b>{vip}</b>\n📅 Membro desde: <code>{p['created_at'][:10]}</code>",back())
def invite(chat,uid):
    p=db.get_profile(uid); link=f"https://t.me/{BOT_USERNAME}?start={uid}"
    send(chat,f"🚀 <b>SEU LINK EXCLUSIVO</b>\n━━━━━━━━━━━━━━━━━━\nConvide amigos. Quando uma pessoa nova iniciar o bot pelo seu link, a indicação será registrada.\n\n🔗 <code>{link}</code>\n👥 Indicações confirmadas: <b>{p['referrals']}</b>\n🎁 Recompensa por indicação: <b>{POINTS_PER_REFERRAL} pontos</b>",[[btn("🏆 Top indicadores","toprefs")],[btn("⬅️ Menu principal","home")]])
def toprefs(chat):
    rows=db.top_referrals(); lines=["🚀 <b>CAMPEÕES DE INDICAÇÃO</b>","━━━━━━━━━━━━━━━━━━"]
    for i,r in enumerate(rows,1): lines.append(f"{i}. <b>{escape((r['first_name'] or str(r['user_id']))[:24])}</b> — {r['referrals']} amigos")
    if not rows: lines.append("As primeiras indicações ainda estão por vir.")
    send(chat,"\n".join(lines),back())
def missions(chat,uid):
    p=db.get_profile(uid); state="Disponível" if p["last_daily"]!=db.today() else "Concluída hoje"
    milestones=db.referral_milestone_status(uid)
    vip_goals=db.referral_vip_status(uid)
    lines=["🎯 <b>MISSÕES DO PIT</b>","━━━━━━━━━━━━━━━━━━",f"🎁 Check-in diário — <i>{state}</i>",f"🚀 Indicações válidas: <b>{p['referrals']}</b>","", "🏆 <b>METAS DE INDICAÇÃO</b>"]
    for item in milestones:
        status="Resgatar bônus" if item["reached"] and not item["claimed"] else ("✅ Recebido" if item["claimed"] else "🔒 Em andamento")
        lines.append(f"{item['milestone']} amigo(s) — bônus de {item['bonus']} pontos — <b>{status}</b>")
    kb=[[btn("🎁 Fazer check-in","daily"),btn("🚀 Convidar","invite")]]
    for item in milestones:
        if item["reached"] and not item["claimed"]: kb.append([btn(f"🎉 Resgatar meta de {item['milestone']} amigo(s)","milestone:"+str(item["milestone"]))])
    lines.extend(["","💎 <b>METAS DO CLUBE VIP</b>"])
    for item in vip_goals:
        status="Resgatar VIP" if item["reached"] and not item["claimed"] else ("✅ Resgatado" if item["claimed"] else "🔒 Em andamento")
        lines.append(f"{item['milestone']} amigos — VIP por {item['days']} dias — <b>{status}</b>")
        if item["reached"] and not item["claimed"]:
            kb.append([btn(f"💎 Resgatar VIP de {item['days']} dias","vipmilestone:"+str(item["milestone"]))])
    kb.append([btn("⬅️ Menu principal","home")])
    send(chat,"\n".join(lines),kb)
def task_list(chat,uid):
    rows=db.active_tasks_for_user(uid)
    if not rows:
        send(chat,"📋 <b>TAREFAS</b>\n\nNo momento não há tarefas disponíveis.",back()); return
    lines=["📋 <b>TAREFAS DISPONÍVEIS</b>","━━━━━━━━━━━━━━━━━━"]
    kb=[]
    for task in rows:
        lines.append(f"\n<b>#{task['id']} — {escape(task['title'])}</b>\n{escape(task['description'])}\n🎁 Recompensa: <b>{task['reward_points']} pontos</b>")
        kb.append([btn(f"Enviar tarefa #{task['id']}","task:"+str(task["id"]))])
    kb.append([btn("⬅️ Menu principal","home")])
    send(chat,"\n".join(lines),kb)


def shop(chat,uid):
    rows=db.active_rewards()
    if not rows:
        send(chat,"🎁 <b>LOJA DE PRÊMIOS</b>\\n\\nAinda não há prêmios disponíveis. Volte mais tarde!",back())
        return
    lines=["🎁 <b>LOJA DE PRÊMIOS</b>","━━━━━━━━━━━━━━━━━━","Escolha o prêmio que deseja solicitar:"]
    kb=[]
    for r in rows:
        stock="Estoque ilimitado" if r["stock"]<0 else f"Estoque: {r['stock']}"
        lines.append(f"\\n<b>{escape(r['title'])}</b> — {r['points_cost']:,} pontos\\n{escape(r['description'])}\\n📦 {stock}")
        kb.append([btn(f"🎁 Solicitar: {r['title'][:24]} ({r['points_cost']} pts)","shopbuy:"+str(r["id"]))])
    kb.append([btn("⬅️ Menu principal","home")])
    send(chat,"\\n".join(lines),kb)

def history(chat,uid):
    rows=db.history(uid,8); lines=["📜 <b>SEU EXTRATO</b>","━━━━━━━━━━━━━━━━━━"]
    if not rows: lines.append("Nenhuma movimentação registrada.")
    for r in rows:
        sign="+" if r["amount"]>0 else ""; icon="🟢" if r["amount"]>0 else "🔴"
        lines.append(f"{icon} <b>{sign}{r['amount']} pts</b> — {escape(r['reason'][:50])}\n<i>{r['created_at']}</i>")
    send(chat,"\n".join(lines),back())
def redeem_help(chat):
    send(chat,"🎟️ <b>CENTRAL DE RESGATES</b>\n━━━━━━━━━━━━━━━━━━\nMínimo: <b>"+str(MIN_REDEEM_POINTS)+" pontos</b>\nEnvie: <code>/resgatar PONTOS DESCRIÇÃO</code>\nExemplo: <code>/resgatar 100 Pix de R$ 5</code>",back())

def notifications_page(chat,uid):
    enabled=db.notifications_enabled(uid)
    state="ATIVADAS ✅" if enabled else "DESATIVADAS 🔕"
    action="notifications:off" if enabled else "notifications:on"
    label="🔕 Desativar notificações" if enabled else "🔔 Ativar notificações"
    send(chat,f"🔔 <b>NOTIFICAÇÕES</b>\n\nStatus atual: <b>{state}</b>\n\nVocê pode escolher se deseja receber avisos sobre aprovações de tarefas, indicações, saques e resgates.",[[btn(label,action)],[btn("⬅️ Menu principal","home")]])

def help_page(chat):
    send(chat,f"❓ <b>CENTRAL DE AJUDA</b>\n━━━━━━━━━━━━━━━━━━\n💰 Pontos: acumule participando das ações.\n🎁 Check-in: bônus uma vez por dia.\n🚀 Indicações: compartilhe seu link pessoal.\n🏆 Ranking: veja os participantes com mais pontos.\n🎟️ Resgates: /resgatar PONTOS DESCRIÇÃO. Mínimo {MIN_REDEEM_POINTS} pontos.\n💎 VIP: ativação pela administração.",back())

def command(m):
    t=m.get("text") or ""; p=t.split(maxsplit=2); cmd=p[0].split("@")[0].lower()
    chat=m["chat"]["id"]; uid=m.get("from",{}).get("id")
    if cmd=="/start": start(m)
    elif cmd=="/saldo": balance(chat,uid)
    elif cmd=="/ranking": ranking_menu(chat)
    elif cmd=="/diario": daily(chat,uid)
    elif cmd=="/novopremio" and admin(uid):
        raw=t.split(maxsplit=1)
        if len(raw)<2:
            send(chat,"Use: /novopremio PONTOS | ESTOQUE | TITULO | DESCRICAO\\nUse -1 no estoque para ilimitado."); return
        parts=[x.strip() for x in raw[1].split("|",3)]
        if len(parts)<4 or not parts[0].isdigit() or not parts[1].lstrip("-").isdigit():
            send(chat,"Use: /novopremio PONTOS | ESTOQUE | TITULO | DESCRICAO"); return
        try:
            rid=db.create_reward(parts[2],parts[3],int(parts[0]),int(parts[1]))
            send(chat,f"✅ Prêmio #{rid} cadastrado na loja!")
        except ValueError as e: send(chat,escape(str(e)))
    elif cmd=="/novatarefa" and admin(uid):
        raw=t.split(maxsplit=1)
        if len(raw)<2 or "|" not in raw[1]:
            send(chat,"Use: /novatarefa PONTOS | TITULO | DESCRICAO"); return
        parts=[x.strip() for x in raw[1].split("|",2)]
        if len(parts)<3 or not parts[0].isdigit():
            send(chat,"Use: /novatarefa PONTOS | TITULO | DESCRICAO"); return
        try:
            task_id=db.create_task(parts[1],parts[2],int(parts[0]),True)
            send(chat,f"✅ Tarefa #{task_id} cadastrada com {int(parts[0])} pontos.")
        except ValueError as e: send(chat,escape(str(e)))
    elif cmd=="/sacar":
        args=t.split(maxsplit=3)
        if len(args)<4 or not args[1].isdigit(): send(chat,"Use: /sacar PONTOS TIPO_CHAVE CHAVE_PIX"); return
        pts=int(args[1]); key_type=args[2].upper(); pix_key=args[3].strip()
        try: rid=db.create_payout_request(uid,pts,pix_key,key_type,MIN_REDEEM_POINTS)
        except ValueError as e: send(chat,escape(str(e))); return
        amount=pts/100
        send(chat,f"✅ Solicitação de saque <b>#{rid}</b> enviada!\nValor: <b>R$ {amount:.2f}</b>\nSeus pontos ficaram reservados até a análise da equipe.")
        for aid in ADMIN_IDS:
            try: send(aid,f"💸 <b>NOVO PEDIDO DE SAQUE #{rid}</b>\nUsuário: <code>{uid}</code>\nPontos: {pts}\nValor: R$ {amount:.2f}\nChave ({escape(key_type)}): <code>{escape(pix_key)}</code>\n\n⚠️ Faça a transferência Pix primeiro. Depois confirme abaixo.",[[btn("✅ Confirmar Pix pago","payout:"+str(rid)+":yes"),btn("❌ Rejeitar pedido","payout:"+str(rid)+":no")]])
            except Exception: log.exception("Falha ao notificar admin sobre saque")
    elif cmd=="/resgatar":
        if len(p)<3 or not p[1].isdigit(): send(chat,"Use /resgatar PONTOS DESCRIÇÃO"); return
        pts=int(p[1]); reward=p[2].strip()
        if pts<MIN_REDEEM_POINTS or pts>10000000 or not reward: send(chat,f"Resgate mínimo: {MIN_REDEEM_POINTS} pontos."); return
        try: rid=db.create_redemption(uid,pts,reward)
        except ValueError as e: send(chat,escape(str(e))); return
        send(chat,f"✅ Pedido #{rid} enviado. Os pontos ficam reservados até análise.")
        for aid in ADMIN_IDS:
            try: send(aid,f"Novo resgate #{rid}\nUsuário: {uid}\nPontos: {pts}\nPrêmio: {escape(reward)}")
            except Exception: log.exception("Falha ao notificar admin")
    elif cmd in ("/admin","/stats","/addpoints","/setvip","/pedidos","/saques","/broadcast","/usuario","/novopremio") and admin(uid):
        if cmd=="/admin": send(chat,"🛠️ <b>PAINEL ADMINISTRATIVO PIT</b>\nEscolha uma função abaixo:",admin_menu())
        elif cmd=="/usuario":
            if len(p)<2 or not p[1].isdigit(): send(chat,"Use /usuario ID"); return
            target=int(p[1]); u=db.get_user(target)
            if not u: send(chat,"Usuário não encontrado."); return
            pr=db.get_profile(target)
            vip="Ativo" if u["is_vip"] else "Inativo"
            send(chat,f"👤 <b>FICHA DO MEMBRO</b>\nID: <code>{target}</code>\nNome: {escape(u['first_name'] or 'Sem nome')}\nUsername: @{escape(u['username'] or 'não informado')}\nSaldo: <b>{pr['points']} pontos</b>\nIndicações: {pr['referrals']}\nVIP: {vip}\nCadastro: {pr['created_at']}")
        elif cmd=="/broadcast":
            if len(p)<2 or not p[1].strip(): send(chat,"Use /broadcast SUA MENSAGEM"); return
            message=escape(t.split(maxsplit=1)[1][:3500])
            sent=0; failed=0
            for target in db.all_user_ids():
                try: send(target,"📢 <b>COMUNICADO PIT PRÊMIOS</b>\n\n"+message); sent+=1
                except Exception: failed+=1
            send(chat,f"📣 <b>Disparo finalizado</b>\nEnviados: {sent}\nFalhas: {failed}")
        elif cmd=="/stats":
            s=db.stats(); send(chat,f"📊 Usuários: {s['users']}\nPontos: {s['points']}\nResgates pendentes: {s['pending']}")
        elif cmd=="/addpoints":
            if len(p)<3 or not p[1].isdigit() or not p[2].lstrip("-").isdigit(): send(chat,"Use /addpoints ID QUANTIDADE"); return
            amount=int(p[2])
            if not amount or abs(amount)>1000000: send(chat,"Quantidade inválida."); return
            try: db.add_points(int(p[1]),amount,f"Ajuste por admin {uid}")
            except ValueError as e: send(chat,escape(str(e))); return
            send(chat,"✅ Saldo atualizado.")
        elif cmd=="/setvip":
            if len(p)<3 or not p[1].isdigit() or p[2].lower() not in ("on","off"): send(chat,"Use /setvip ID on|off"); return
            db.set_vip(int(p[1]),p[2].lower()=="on"); send(chat,"✅ VIP atualizado.")
        elif cmd=="/saques":
            rows=db.pending_payouts()
            if not rows: send(chat,"Nenhum saque pendente."); return
            for r in rows:
                amount=r["amount_cents"]/100
                kb=[[btn("✅ Confirmar Pix pago","payout:"+str(r["id"])+":yes"),btn("❌ Rejeitar","payout:"+str(r["id"])+":no")]]
                send(chat,f"💸 <b>SAQUE #{r['id']}</b>\nUsuário: <code>{r['user_id']}</code>\nValor: R$ {amount:.2f}\nPontos: {r['points']}\nChave ({escape(r['pix_key_type'])}): <code>{escape(r['pix_key'])}</code>\n\n⚠️ Transfira o Pix antes de confirmar.",kb)
        elif cmd=="/pedidos":
            rows=db.pending_redemptions()
            if not rows: send(chat,"Nenhum pedido pendente."); return
            for r in rows:
                kb=[[{"text":"Aprovar","callback_data":f"review:{r['id']}:yes"},{"text":"Rejeitar","callback_data":f"review:{r['id']}:no"}]]
                send(chat,f"Pedido #{r['id']}\nUsuário: {r['user_id']}\nPontos: {r['points']}\nPrêmio: {escape(r['reward'])}",kb)
    elif cmd in ("/admin","/stats","/addpoints","/setvip","/pedidos","/saques","/broadcast","/usuario","/novopremio"): pass
    else: send(chat,"Não entendi. Use /start para abrir o menu.")

def callback(c):
    data=c.get("data",""); uid=c.get("from",{}).get("id"); msg=c.get("message",{}); chat=msg.get("chat",{}).get("id")
    api("answerCallbackQuery",{"callback_query_id":c["id"]})
    if chat is None: return
    navigation_actions={"home","profile","wallet","invite","toprefs","missions","history","help","redeem_info","balance","ranking","daily","vip","help_redeem","tasks","notifications","ranking:weekly","ranking:general","shop"}
    if (data in navigation_actions or data.startswith("task:")) and msg.get("message_id"):
        try: api("deleteMessage",{"chat_id":chat,"message_id":msg["message_id"]})
        except Exception: log.warning("Não foi possível apagar a mensagem anterior do bot")
    if data.startswith("admin:"):
        if not admin(uid): return
        action=data.split(":",1)[1]
        if action=="stats":
            st=db.stats(); send(chat,f"📊 <b>ESTATÍSTICAS DO PIT</b>\nUsuários: <b>{st['users']}</b>\nPontos em circulação: <b>{st['points']}</b>\nResgates pendentes: <b>{st['pending']}</b>",admin_menu())
        elif action=="user": send(chat,"👤 Para consultar um membro, envie:\n<code>/usuario ID</code>",admin_menu())
        elif action=="add": send(chat,"➕ Para adicionar ou retirar pontos, envie:\n<code>/addpoints ID QUANTIDADE</code>\nUse quantidade negativa para retirar.",admin_menu())
        elif action=="vip": send(chat,"💎 Para ativar ou desativar o VIP, envie:\n<code>/setvip ID on</code> ou <code>/setvip ID off</code>",admin_menu())
        elif action=="broadcast": send(chat,"📢 Para enviar um comunicado a todos os usuários, envie:\n<code>/broadcast SUA MENSAGEM</code>",admin_menu())
        elif action=="rewardorders":
            rows=db.pending_reward_orders()
            if not rows: send(chat,"🎁 Nenhum pedido da loja aguardando análise.",admin_menu()); return
            for r in rows:
                kb=[[btn("✅ Aprovar pedido","rewardreview:"+str(r["id"])+":yes"),btn("❌ Rejeitar","rewardreview:"+str(r["id"])+":no")]]
                send(chat,f"🎁 <b>PEDIDO DA LOJA #{r['id']}</b>\\nPrêmio: {escape(r['title'])}\\nUsuário: <code>{r['user_id']}</code>\\nPontos: {r['points_spent']}",kb)
        elif action=="orders":
            rows=db.pending_redemptions()
            if not rows: send(chat,"Nenhum resgate pendente.",admin_menu())
            for r in rows:
                kb=[[btn("✅ Aprovar","review:"+str(r["id"])+":yes"),btn("❌ Rejeitar","review:"+str(r["id"])+":no")]]
                send(chat,f"🎟️ <b>RESGATE #{r['id']}</b>\nUsuário: <code>{r['user_id']}</code>\nPontos: {r['points']}\nPrêmio: {escape(r['reward'])}",kb)
        elif action=="manage_tasks":
            rows=db.active_tasks()
            if not rows:
                send(chat,"🗂️ Não há tarefas ativas para apagar.",admin_menu()); return
            send(chat,"🗂️ <b>GERENCIAR TAREFAS</b>\\nEscolha a tarefa que deseja retirar da lista dos usuários:",[[btn("🗑️ #"+str(row["id"])+" — "+row["title"][:30],"taskdisable:"+str(row["id"]))] for row in rows]+[[btn("⬅️ Voltar ao painel","admin:back")]])
        elif action=="back":
            send(chat,"🛠️ <b>PAINEL ADMINISTRATIVO PIT</b>\\nEscolha uma função abaixo:",admin_menu())
        elif action=="tasks":
            rows=db.pending_task_submissions()
            if not rows: send(chat,"📋 Nenhuma tarefa aguardando revisão.",admin_menu()); return
            for row in rows:
                kb=[[btn("✅ Aprovar pontos","taskreview:"+str(row["id"])+":yes"),btn("❌ Rejeitar","taskreview:"+str(row["id"])+":no")]]
                proof=row["proof"] or ""
                caption=f"📋 <b>COMPROVAÇÃO DE TAREFA #{row['id']}</b>\nTarefa: {escape(row['title'])}\nUsuário: <code>{row['user_id']}</code> ({escape(row['first_name'] or 'Sem nome')})\nRecompensa: {row['reward_points']} pontos"
                if proof.startswith("photo:"):
                    api("sendPhoto",{"chat_id":chat,"photo":proof.split(":",1)[1],"caption":caption,"parse_mode":"HTML","reply_markup":{"inline_keyboard":kb}})
                else:
                    send(chat,caption+"\nComprovação: "+escape(proof),kb)
        elif action=="fraud":
            rows=db.pending_referral_reviews()
            if not rows: send(chat,"🛡️ Nenhuma indicação aguardando análise.",admin_menu()); return
            for r in rows:
                kb=[[btn("✅ Aprovar indicação","refreview:"+str(r["id"])+":yes"),btn("❌ Rejeitar","refreview:"+str(r["id"])+":no")]]
                send(chat,f"🛡️ <b>ANÁLISE #{r['id']}</b>\nIndicador: <code>{r['referrer_id']}</code>\nNovo usuário: <code>{r['referred_user_id']}</code>\nNome: {escape(r['first_name'] or 'Sem nome')}\nMotivo: {escape(r['risk_reason'])}",kb)
        elif action=="payouts":
            rows=db.pending_payouts()
            if not rows: send(chat,"Nenhum saque pendente.",admin_menu())
            for r in rows:
                amount=r["amount_cents"]/100
                kb=[[btn("✅ Confirmar Pix pago","payout:"+str(r["id"])+":yes"),btn("❌ Rejeitar pedido","payout:"+str(r["id"])+":no")]]
                send(chat,f"💸 <b>SAQUE #{r['id']}</b>\nUsuário: <code>{r['user_id']}</code>\nValor: R$ {amount:.2f}\nPontos: {r['points']}\nChave ({escape(r['pix_key_type'])}): <code>{escape(r['pix_key'])}</code>",kb)
        return
    if data=="notifications":
        notifications_page(chat,uid)
    elif data=="notifications:on":
        db.set_notifications(uid,True); notifications_page(chat,uid)
    elif data=="notifications:off":
        db.set_notifications(uid,False); notifications_page(chat,uid)
    elif data=="home": send_photo(chat,BANNER_URL,"🐾 <b>PIT PRÊMIOS</b>\nSua central de pontos, conquistas e recompensas.",menu())
    elif data=="tasks": task_list(chat,uid)
    elif data=="shop": shop(chat,uid)
    elif data.startswith("shopbuy:"):
        try:
            reward_id=int(data.split(":",1)[1])
            order_id=db.create_reward_order(uid,reward_id)
            send(chat,f"✅ Seu pedido da loja foi enviado!\\nNúmero: <b>#{order_id}</b>\\nOs pontos foram reservados até a análise da equipe.",back())
            for aid in ADMIN_IDS:
                try: send(aid,f"🎁 <b>NOVO PEDIDO DA LOJA #{order_id}</b>\\nUsuário: <code>{uid}</code>",[[btn("Revisar pedidos da loja","admin:rewardorders")]])
                except Exception: log.exception("Falha ao avisar admin sobre pedido da loja")
        except (ValueError,IndexError) as e: send(chat,escape(str(e)),back())
    elif data.startswith("task:"):
        try:
            task_id=int(data.split(":")[1])
            task=next((x for x in db.active_tasks_for_user(uid) if x["id"]==task_id),None)
            if not task: send(chat,"Essa tarefa não está mais disponível."); return
            PENDING_TASK_PROOFS[uid]=task_id
            send(chat,f"📋 <b>ENVIAR COMPROVAÇÃO</b>\nTarefa: {escape(task['title'])}\nRecompensa: {task['reward_points']} pontos\n\nEnvie agora o <b>PRINT (FOTO) OU UMA MENSAGEM</b> como comprovante. A equipe vai analisar antes de liberar os pontos.")
        except (ValueError,IndexError): send(chat,"Tarefa inválida.")
    elif data=="profile": profile(chat,uid)
    elif data=="wallet": balance(chat,uid)
    elif data=="invite": invite(chat,uid)
    elif data=="toprefs": toprefs(chat)
    elif data=="missions": missions(chat,uid)
    elif data=="history": history(chat,uid)
    elif data=="help": help_page(chat)
    elif data=="redeem_info": redeem_help(chat)
    elif data=="balance": balance(chat,uid)
    elif data=="ranking": ranking_menu(chat)
    elif data=="ranking:general": ranking(chat)
    elif data=="ranking:weekly": weekly_ranking(chat)
    elif data=="daily": daily(chat,uid)
    elif data=="vip":
        u=db.get_user(uid); send(chat,"💎 VIP: "+("ATIVO" if u and u["is_vip"] else "INATIVO")+". Consulte a administração.")
    elif data=="help_redeem": send(chat,f"Para solicitar: /resgatar PONTOS DESCRIÇÃO\nMínimo: {MIN_REDEEM_POINTS} pontos.")
    elif data.startswith("milestone:"):
        try:
            milestone=int(data.split(":")[1]); bonus=db.claim_referral_milestone(uid,milestone)
            send(chat,f"🎉 Meta concluída! Você recebeu <b>{bonus} pontos</b> de bônus.")
        except (ValueError,IndexError) as e: send(chat,escape(str(e)))
    elif data.startswith("vipmilestone:"):
        try:
            milestone=int(data.split(":")[1]); days,expiry=db.claim_referral_vip(uid,milestone)
            send(chat,f"💎 <b>PARABÉNS! VIP ATIVADO!</b>\nVocê ganhou <b>{days} dias de Clube VIP</b>.\nValidade até: <b>{escape(expiry)}</b>.")
        except (ValueError,IndexError) as e: send(chat,escape(str(e)))
    elif data.startswith("taskdisable:"):
        if not admin(uid): return
        try:
            task_id=int(data.split(":")[1])
            if db.deactivate_task(task_id):
                send(chat,f"✅ Tarefa #{task_id} foi retirada das tarefas disponíveis. Os registros e comprovantes foram preservados.",[[btn("🗂️ Gerenciar tarefas","admin:manage_tasks")],[btn("⬅️ Painel admin","admin:back")]])
            else:
                send(chat,"Essa tarefa já foi retirada ou não existe.",[[btn("🗂️ Gerenciar tarefas","admin:manage_tasks")]])
        except (ValueError,IndexError):
            send(chat,"Identificação de tarefa inválida.")
    elif data.startswith("taskreview:"):
        if not admin(uid): return
        _,sid,decision=data.split(":")
        result=db.review_task_submission(int(sid),uid,decision=="yes")
        if not result: send(chat,"Essa tarefa já foi analisada."); return
        status="aprovada; pontos creditados" if decision=="yes" else "rejeitada"
        if msg.get("photo"):
            api("editMessageCaption",{"chat_id":chat,"message_id":msg["message_id"],"caption":msg.get("caption","")+f"\n\n<b>Status:</b> {status}","parse_mode":"HTML"})
        else:
            api("editMessageText",{"chat_id":chat,"message_id":msg["message_id"],"text":msg.get("text","")+f"\n\n<b>Status:</b> {status}","parse_mode":"HTML"})
        try: notify_user(result["user_id"],f"📋 Sua comprovação da tarefa <b>{escape(result['title'])}</b> foi {status}.")
        except Exception: log.exception("Falha ao notificar usuário sobre tarefa")
    elif data.startswith("refreview:"):
        if not admin(uid): return
        _,rid,decision=data.split(":"); result=db.review_referral(int(rid),uid,decision=="yes")
        if not result: send(chat,"Esta indicação já foi analisada."); return
        status="aprovada" if decision=="yes" else "rejeitada"
        api("editMessageText",{"chat_id":chat,"message_id":msg["message_id"],"text":msg.get("text","")+f"\n\nStatus: {status}","parse_mode":"HTML"})
        try:
            if decision=="yes": notify_user(result["referrer_id"],"🎉 Sua indicação foi aprovada na análise de segurança! Os pontos foram creditados na sua carteira.")
            else: notify_user(result["referrer_id"],"⚠️ Uma indicação não foi aprovada na análise de segurança e não gerou pontos.")
        except Exception: log.exception("Falha ao notificar resultado da análise")
    elif data.startswith("payout:"):
        if not admin(uid): return
        _,rid,decision=data.split(":"); result=db.review_payout(int(rid),uid,decision=="yes")
        if not result: send(chat,"Este pedido já foi analisado."); return
        approved=decision=="yes"
        status="aprovado" if approved else "rejeitado; os pontos foram devolvidos"
        api("editMessageText",{"chat_id":chat,"message_id":msg["message_id"],"text":msg.get("text","")+f"\nStatus: {status}","parse_mode":"HTML"})
        try:
            if approved: notify_user(result["user_id"],f"🎉 <b>Parabéns! Seu saque foi aprovado!</b>\n\nO pagamento de <b>R$ {result['amount_cents']/100:.2f}</b> foi enviado para sua chave Pix. Obrigado por participar do PIT PRÊMIOS! 🐾")
            else: notify_user(result["user_id"],f"❌ Seu saque #{rid} foi rejeitado. Seus pontos foram devolvidos à carteira.")
        except Exception: log.exception("Falha ao avisar usuário sobre saque")
    elif data.startswith("rewardreview:"):
        if not admin(uid): return
        _,rid,decision=data.split(":")
        result=db.review_reward_order(int(rid),uid,decision=="yes")
        if not result: send(chat,"Este pedido já foi analisado."); return
        status="aprovado" if decision=="yes" else "rejeitado; os pontos foram devolvidos e o estoque restaurado"
        api("editMessageText",{"chat_id":chat,"message_id":msg["message_id"],"text":msg.get("text","")+f"\\n\\nStatus: {status}","parse_mode":"HTML"})
        try: notify_user(result["user_id"],f"🎁 Seu pedido de recompensa #{rid} foi {status}.")
        except Exception: log.exception("Falha ao avisar usuário sobre pedido da loja")
    elif data.startswith("review:"):
        if not admin(uid): return
        _,rid,decision=data.split(":"); result=db.review_redemption(int(rid),uid,decision=="yes")
        if not result: return
        status="aprovado" if decision=="yes" else "rejeitado; pontos devolvidos"
        api("editMessageText",{"chat_id":chat,"message_id":msg["message_id"],"text":msg.get("text","")+f"\nStatus: {status}","parse_mode":"HTML"})
        try: notify_user(result["user_id"],f"Seu resgate #{rid} foi {status}.")
        except Exception: log.exception("Falha ao avisar usuário")

def main():
    global BOT_USERNAME
    db.init_db(); me=api("getMe"); BOT_USERNAME=me.get("username",""); log.warning("PIT PRÊMIOS iniciado como @%s",BOT_USERNAME)
    offset=None
    while True:
        try:
            q={"timeout":25,"allowed_updates":["message","callback_query"]}
            if offset is not None: q["offset"]=offset
            for update in api("getUpdates",q):
                offset=update["update_id"]+1
                try:
                    if "message" in update:
                        m=update["message"]
                        if (m.get("text") or "").startswith("/"): command(m)
                        elif m.get("chat",{}).get("type")=="private":
                            uid=m.get("from",{}).get("id"); task_id=PENDING_TASK_PROOFS.pop(uid,None)
                            if task_id:
                                try:
                                    photo=m.get("photo")
                                    if photo:
                                        proof="photo:"+photo[-1]["file_id"]
                                    else:
                                        proof=(m.get("text") or "").strip()
                                    submission_id=db.submit_task(task_id,uid,proof)
                                    send(m["chat"]["id"],"✅ Comprovação enviada! A equipe vai analisar sua tarefa.")
                                    for aid in ADMIN_IDS:
                                        if proof.startswith("photo:"):
                                            api("sendPhoto",{"chat_id":aid,"photo":proof.split(":",1)[1],"caption":f"📋 <b>NOVA COMPROVAÇÃO #{submission_id}</b>\nUsuário: <code>{uid}</code>\nTarefa: #{task_id}","parse_mode":"HTML","reply_markup":{"inline_keyboard":[[btn("Revisar tarefas","admin:tasks")]]}})
                                        else:
                                            send(aid,f"📋 <b>NOVA COMPROVAÇÃO #{submission_id}</b>\nUsuário: <code>{uid}</code>\nTarefa: #{task_id}\nComprovação: {escape(proof[:1000])}",[[btn("Revisar tarefas","admin:tasks")]])
                                except ValueError as e: send(m["chat"]["id"],escape(str(e)))
                            else: send(m["chat"]["id"],"Não entendi. Use /start para abrir o menu.")
                    elif "callback_query" in update: callback(update["callback_query"])
                except Exception: log.exception("Erro ao processar atualização %s",update.get("update_id"))
        except KeyboardInterrupt: break
        except Exception: log.exception("Falha na conexão; nova tentativa em 5 segundos"); time.sleep(5)

if __name__=="__main__": main()
