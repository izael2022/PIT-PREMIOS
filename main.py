import json, logging, time, threading, urllib.parse, urllib.request, urllib.error, sqlite3, tempfile, os, queue, zipfile, io, platform
from html import escape
import database as db
from config import BOT_TOKEN, ADMIN_IDS, POINTS_PER_REFERRAL, DAILY_REWARD, MIN_REDEEM_POINTS, DATABASE_PATH

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
log=logging.getLogger("pit_premios")
API=f"https://api.telegram.org/bot{BOT_TOKEN}/"
BOT_USERNAME=""
PENDING_TASK_PROOFS={}
BANNER_URL="https://raw.githubusercontent.com/izael2022/PIT-PREMIOS/main/assets/pit_premios_banner.jpg"

def api(method, data=None):
    payload=urllib.parse.urlencode({k: json.dumps(v, ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in (data or {}).items()}).encode()
    attempts=4 if method=="getUpdates" else 1
    for attempt in range(attempts):
        req=urllib.request.Request(API+method,data=payload)
        try:
            with urllib.request.urlopen(req,timeout=35 if method=="getUpdates" else 25) as response:
                result=json.loads(response.read())
            if not result.get("ok"):
                error_code=result.get("error_code")
                if method=="getUpdates" and error_code in (429,500,502,503,504) and attempt<attempts-1:
                    retry_after=result.get("parameters",{}).get("retry_after",2)
                    time.sleep(max(1,min(int(retry_after),15)))
                    continue
                raise RuntimeError(str(result))
            return result.get("result")
        except urllib.error.HTTPError as e:
            detail=e.read().decode("utf-8","replace")[:500]
            if method=="getUpdates" and e.code in (429,500,502,503,504) and attempt<attempts-1:
                retry_after=2
                try:
                    parsed=json.loads(detail)
                    retry_after=parsed.get("parameters",{}).get("retry_after",2)
                except Exception:
                    pass
                time.sleep(max(1,min(int(retry_after),15)))
                continue
            raise RuntimeError(f"Telegram HTTP {e.code}: {detail}") from e
        except (urllib.error.URLError,TimeoutError,ConnectionError,OSError) as e:
            if method=="getUpdates" and attempt<attempts-1:
                time.sleep(min(2**attempt,8))
                continue
            raise
    raise RuntimeError("Não foi possível consultar atualizações do Telegram após várias tentativas.")

OUTBOUND_QUEUE=queue.Queue(maxsize=500)
OUTBOUND_READY=False
OUTBOUND_STOP=threading.Event()

def _outbound_worker():
    last_chat={}
    while not OUTBOUND_STOP.is_set():
        try:
            item=OUTBOUND_QUEUE.get(timeout=1)
        except queue.Empty:
            continue
        chat,text_value,keyboard,future=item
        try:
            wait=max(0,1.05-(time.monotonic()-last_chat.get(str(chat),0)))
            if wait: time.sleep(wait)
            payload={"chat_id":chat,"text":text_value,"parse_mode":"HTML"}
            if keyboard: payload["reply_markup"]={"inline_keyboard":keyboard}
            result=api("sendMessage",payload)
            last_chat[str(chat)]=time.monotonic()
            future.set_result(result)
        except Exception as exc:
            future.set_exception(exc)
            log.exception("Falha no envio para chat %s",chat)
        finally:
            OUTBOUND_QUEUE.task_done()

def start_outbound_worker():
    global OUTBOUND_READY
    if not OUTBOUND_READY:
        threading.Thread(target=_outbound_worker,name="pit-outbound",daemon=True).start()
        OUTBOUND_READY=True

def send(chat, text, keyboard=None):
    if not OUTBOUND_READY:
        d={"chat_id":chat,"text":text,"parse_mode":"HTML"}
        if keyboard: d["reply_markup"]={"inline_keyboard":keyboard}
        return api("sendMessage",d)
    from concurrent.futures import Future
    future=Future()
    OUTBOUND_QUEUE.put((chat,text,keyboard,future),timeout=30)
    return future.result(timeout=90)

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
            [btn("🚀 Convidar","invite"),btn("👥 Meus convidados","myrefs")],
            [btn("💎 Clube VIP","vip"),btn("🎟️ Resgatar","redeem_info")],
            [btn("🎁 Loja de prêmios","shop"),btn("📦 Meus pedidos","myorders")],
            [btn("📜 Extrato","history"),btn("💸 Meus saques","mypayouts")],
            [btn("🔔 Notificações","notifications")],
            [btn("❓ Ajuda","help")],
            [btn("📋 Tarefas disponíveis","tasks"),btn("📨 Minhas tarefas enviadas","mytasks")]]
def back(): return [[btn("⬅️ Menu principal","home")]]

def admin_menu():
    return [[btn("📊 Estatísticas","admin:stats"),btn("👤 Consultar usuário","admin:user")],
            [btn("➕ Adicionar pontos","admin:add"),btn("💎 Gerenciar VIP","admin:vip")],
            [btn("🎟️ Resgates","admin:orders"),btn("💸 Saques Pix","admin:payouts")],
            [btn("🎁 Pedidos da loja","admin:rewardorders")],
            [btn("🗂️ Gerenciar prêmios","admin:managerewards")],
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
    send(chat,"🏆 <b>RANKING PIT PRÊMIOS</b>\n\nEscolha qual classificação deseja consultar:",[[btn("📅 Ranking semanal — últimos 7 dias","ranking:weekly")],[btn("🏆 Ranking geral — pontos acumulados","ranking:general")],[btn("⬅️ Menu principal","home")]])

def weekly_ranking(chat):
    lines=["📅 <b>TOP 10 DA SEMANA</b>","<i>Pontos ganhos nos últimos 7 dias.</i>","━━━━━━━━━━━━━━━━━━"]
    rows=db.weekly_ranking()
    if not rows:
        lines.append("Ainda não há pontos registrados nesta semana. Participe das missões e atividades!")
    for i,u in enumerate(rows,1):
        name=u["first_name"] or ("@"+u["username"] if u["username"] else str(u["user_id"]))
        lines.append(f"{i}. {escape(name)} — <b>{u['points']} pts</b>")
    send(chat,"\n".join(lines),[[btn("🏆 Ver ranking geral","ranking:general")],[btn("⬅️ Voltar","ranking")]])

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
def my_referrals(chat,uid):
    rows=db.user_referrals(uid,15)
    lines=["👥 <b>MEUS CONVIDADOS</b>","━━━━━━━━━━━━━━━━━━"]
    if not rows:
        lines.append("Você ainda não possui convidados.")
    labels={"pending":"⏳ Em análise","approved":"✅ Válida","rejected":"❌ Não aprovada"}
    for r in rows:
        name=escape((r["first_name"] or "Participante")[:35])
        username="@"+escape(r["username"]) if r["username"] else "sem username"
        status=labels.get(r["referral_status"],r["referral_status"])
        lines.append(f"\n<b>{name}</b> ({username})\nID: <code>{r['user_id']}</code>\nStatus: {status}\nCadastro: {r['created_at']}")
    lines.append("\n<i>Mostrando os últimos 15 convidados.</i>")
    send(chat,"\n".join(lines),[[btn("🚀 Voltar a convidar","invite")],[btn("⬅️ Menu principal","home")]])

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
        send(chat,"📋 <b>TAREFAS DISPONÍVEIS</b>\n━━━━━━━━━━━━━━━━━━\n\nNo momento não há tarefas novas para você.\n\n💡 Se uma tarefa foi rejeitada, ela poderá aparecer novamente para você corrigir e reenviar.",[[btn("📨 Minhas tarefas enviadas","mytasks")],[btn("⬅️ Menu principal","home")]])
        return
    lines=["📋 <b>TAREFAS DISPONÍVEIS</b>","━━━━━━━━━━━━━━━━━━","Escolha uma tarefa, leia as instruções e envie uma comprovação válida."]
    kb=[]
    for task in rows:
        proof="📸 Envie print ou foto como comprovante." if task["requires_proof"] else "📝 Envie uma mensagem ou anexo como comprovação."
        lines.append(f"\n<b>🎯 TAREFA #{task['id']} — {escape(task['title'])}</b>\n{escape(task['description'])}\n🎁 Recompensa: <b>{task['reward_points']:,} pontos</b>\n{proof}")
        kb.append([btn(f"📨 Fazer tarefa #{task['id']}","task:"+str(task["id"]))])
    kb.extend([[btn("📨 Minhas tarefas enviadas","mytasks")],[btn("⬅️ Menu principal","home")]])
    send(chat,"\n".join(lines),kb)


def my_task_submissions(chat,uid):
    rows=db.user_task_submissions(uid)
    lines=["📨 <b>MINHAS TAREFAS ENVIADAS</b>","━━━━━━━━━━━━━━━━━━","Acompanhe aqui a análise de cada comprovação."]
    if not rows:
        lines.append("\nVocê ainda não enviou nenhuma tarefa. Acesse Tarefas disponíveis para começar!")
    labels={"pending":"⏳ Aguardando análise da equipe","approved":"✅ Aprovada — pontos creditados","rejected":"❌ Rejeitada — pode corrigir e reenviar"}
    kb=[]
    for row in rows:
        status=labels.get(row["status"],row["status"])
        lines.append(f"\n<b>#{row['task_id']} — {escape(row['title'])}</b>\n🎁 Recompensa: <b>{row['reward_points']:,} pontos</b>\nStatus: <b>{status}</b>\n📨 Tentativas: {row['attempts']}\nÚltimo envio: {row['created_at']}")
        if row["status"]=="rejected":
            kb.append([btn(f"🔄 Corrigir e reenviar #{row['task_id']}","task:"+str(row["task_id"]))])
        elif row["status"]=="pending":
            lines.append("🕒 Sua comprovação está na fila de análise. Aguarde a equipe.")
    kb.extend([[btn("📋 Ver tarefas disponíveis","tasks")],[btn("⬅️ Menu principal","home")]])
    send(chat,"\n".join(lines),kb)

def shop(chat,uid):
    rows=db.active_rewards()
    if not rows:
        send(chat,"🎁 <b>LOJA DE PRÊMIOS</b>\n\nAinda não há prêmios disponíveis. Volte mais tarde!",back())
        return
    lines=["🎁 <b>LOJA DE PRÊMIOS</b>","━━━━━━━━━━━━━━━━━━","Escolha o prêmio que deseja solicitar:"]
    kb=[]
    for r in rows:
        stock="Estoque ilimitado" if r["stock"]<0 else f"Estoque: {r['stock']}"
        lines.append(f"\n<b>{escape(r['title'])}</b> — {r['points_cost']:,} pontos\n{escape(r['description'])}\n📦 {stock}")
        kb.append([btn(f"🎁 Solicitar: {r['title'][:24]} ({r['points_cost']} pts)","shopbuy:"+str(r["id"]))])
    kb.append([btn("⬅️ Menu principal","home")])
    send(chat,"\n".join(lines),kb)


def my_reward_orders(chat,uid):
    rows=db.user_reward_orders(uid)
    lines=["📦 <b>MEUS PEDIDOS DA LOJA</b>","━━━━━━━━━━━━━━━━━━"]
    if not rows:
        lines.append("Você ainda não solicitou nenhum prêmio.")
    kb=[]
    labels={"pending":"⏳ Aguardando análise","approved":"✅ Aprovado","rejected":"❌ Rejeitado","cancelled":"🚫 Cancelado — pontos devolvidos"}
    for r in rows:
        status=labels.get(r["status"],r["status"])
        lines.append(f"\n<b>Pedido #{r['id']}</b> — {escape(r['title'])}\n💰 {r['points_spent']} pontos\nStatus: {status}\nData: {r['created_at']}")
        if r["status"]=="pending":
            kb.append([btn("🚫 Cancelar pedido #"+str(r["id"]),"rewardcancel:"+str(r["id"]))])
    kb.extend([[btn("🎁 Voltar à loja","shop")],[btn("⬅️ Menu principal","home")]])
    send(chat,"\n".join(lines),kb)

def my_payouts(chat,uid):
    rows=db.user_payout_requests(uid)
    lines=["💸 <b>MEUS SAQUES</b>","━━━━━━━━━━━━━━━━━━"]
    if not rows:
        lines.append("Você ainda não solicitou nenhum saque.")
    labels={"pending":"⏳ Aguardando análise","approved":"✅ Pagamento confirmado","rejected":"❌ Rejeitado — pontos devolvidos","cancelled":"🚫 Cancelado — pontos devolvidos"}
    kb=[]
    for row in rows:
        pix=row["pix_key"] or ""
        masked=(pix[:2]+"••••"+pix[-2:]) if len(pix)>6 else ("••••" if pix else "não informada")
        lines.append(f"\n<b>Saque #{row['id']}</b> — R$ {row['amount_cents']/100:.2f}\n💰 {row['points']:,} pontos\nStatus: <b>{labels.get(row['status'],row['status'])}</b>\nChave {escape(row['pix_key_type'])}: <code>{escape(masked)}</code>\nSolicitado: {row['created_at']}")
        if row["status"]=="pending":
            kb.append([btn("🚫 Cancelar saque #"+str(row["id"]),"payoutcancel:"+str(row["id"]))])
    kb.append([btn("⬅️ Menu principal","home")])
    send(chat,"\n".join(lines),kb)

def history(chat,uid,page=0):
    page=max(0,int(page)); page_size=8
    rows=db.history(uid,page_size,page*page_size)
    lines=["📜 <b>SEU EXTRATO</b>","━━━━━━━━━━━━━━━━━━",f"Página <b>{page+1}</b>"]
    if not rows:
        lines.append("Nenhuma movimentação registrada nesta página.")
    for r in rows:
        sign="+" if r["amount"]>0 else ""; icon="🟢" if r["amount"]>0 else "🔴"
        lines.append(f"{icon} <b>{sign}{r['amount']} pts</b> — {escape(r['reason'][:50])}\n<i>{r['created_at']}</i>")
    kb=[]
    if page>0: kb.append(btn("⬅️ Anterior","history:"+str(page-1)))
    if len(rows)==page_size: kb.append(btn("Próxima ➡️","history:"+str(page+1)))
    keyboard=[kb] if kb else []
    keyboard.append([btn("⬅️ Menu principal","home")])
    send(chat,"\n".join(lines),keyboard)
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
    if uid and not admin(uid):
        block=db.get_account_block(uid)
        if block:
            send(chat,"🚫 <b>CONTA BLOQUEADA</b>\\n\\nSeu acesso ao PIT PRÊMIOS está temporariamente bloqueado.\\nMotivo: "+escape(block["reason"])+"\\n\\nSe acredita que houve um engano, entre em contato com a equipe responsável.")
            return
    if uid in ADMIN_IDS and cmd not in ("/admin","/stats"):
        try: db.log_admin_action(uid,cmd," ".join(p[1:])[:300])
        except Exception: log.exception("Falha ao registrar auditoria administrativa")
    if cmd=="/start": start(m)
    elif cmd=="/saldo": balance(chat,uid)
    elif cmd=="/ranking": ranking_menu(chat)
    elif cmd=="/diario": daily(chat,uid)
    elif cmd=="/novopremio" and admin(uid):
        raw=t.split(maxsplit=1)
        if len(raw)<2:
            send(chat,"Use: /novopremio PONTOS | ESTOQUE | TITULO | DESCRICAO\nUse -1 no estoque para ilimitado."); return
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
    elif cmd in ("/admin","/stats","/addpoints","/setvip","/pedidos","/saques","/broadcast","/usuario","/novopremio","/risco","/monitorarindicacoes","/bloquear","/desbloquear","/bloqueados","/historicoantifraude","/saude","/auditoria") and admin(uid):
        if cmd=="/saude":
            try:
                import resource
                rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024
            except Exception: rss=-1
            send(chat,f"🩺 <b>SAÚDE DO PIT PRÊMIOS</b>\\nRAM pico: <b>{rss:.1f} MB</b>\\nTrabalhadores: <b>{WORKERS}</b>\\nFila de envio: <b>{OUTBOUND_QUEUE.qsize()}</b>\\nEstado: <b>online</b>")
        elif cmd=="/auditoria":
            rows=db.recent_admin_audit(20)
            lines=["🧾 <b>ÚLTIMAS AÇÕES ADMINISTRATIVAS</b>"]
            for row in rows: lines.append(f"\\n{row['created_at']} — admin <code>{row['admin_id']}</code>\\n{escape(row['action'])}: {escape(row['details'])}")
            send(chat,"\\n".join(lines) if rows else "Ainda não há ações administrativas registradas.")
        elif cmd=="/bloquear":
            if len(p)<3 or not p[1].isdigit() or not p[2].strip():
                send(chat,"Use: /bloquear ID MOTIVO"); return
            target=int(p[1])
            if target in ADMIN_IDS:
                send(chat,"⛔ Por segurança, não é permitido bloquear uma conta de administrador."); return
            reason=t.split(maxsplit=2)[2]
            if not db.block_account(target,uid,reason):
                send(chat,"Usuário não encontrado no banco de dados."); return
            try: send(target,"🚫 <b>SUA CONTA FOI BLOQUEADA</b>\\nMotivo: "+escape(reason)+"\\nEntre em contato com a equipe se precisar contestar.")
            except Exception: log.warning("Não foi possível notificar usuário bloqueado %s",target)
            send(chat,f"✅ Conta <code>{target}</code> bloqueada. Cadastro, saldo e histórico foram preservados.")
        elif cmd=="/bloqueados":
            rows=db.list_blocked_accounts(30)
            if not rows:
                send(chat,"🛡️ Não há contas bloqueadas no momento."); return
            lines=["🚫 <b>CONTAS BLOQUEADAS</b>","━━━━━━━━━━━━━━━━━━"]
            for row in rows:
                name=escape(row["first_name"] or "Sem nome")
                lines.append(f"\\n<b>{name}</b> — <code>{row['user_id']}</code>\\nMotivo: {escape(row['reason'])}\\nBloqueada em: {row['blocked_at']}\\nPor admin: <code>{row['blocked_by']}</code>")
            send(chat,"\\n".join(lines),admin_menu())
        elif cmd=="/historicoantifraude":
            if len(p)<2 or not p[1].isdigit():
                send(chat,"Use: /historicoantifraude ID"); return
            target=int(p[1]); rows=db.account_block_history(target)
            if not rows:
                send(chat,"Não há histórico de bloqueios para esse usuário."); return
            lines=[f"🧾 <b>HISTÓRICO DE BLOQUEIO</b>\\nUsuário: <code>{target}</code>","━━━━━━━━━━━━━━━━━━"]
            for row in rows:
                action="🔒 BLOQUEADO" if row["action"]=="blocked" else "🔓 DESBLOQUEADO"
                lines.append(f"\\n{action} — {row['created_at']}\\nAdmin: <code>{row['admin_id']}</code>\\nMotivo: {escape(row['reason'] or 'Não informado')}")
            send(chat,"\\n".join(lines),admin_menu())
        elif cmd=="/desbloquear":
            if len(p)<2 or not p[1].isdigit():
                send(chat,"Use: /desbloquear ID"); return
            target=int(p[1])
            if target in ADMIN_IDS:
                send(chat,"⛔ Administradores não podem ser alterados por este comando."); return
            if not db.unblock_account(target,uid):
                send(chat,"Esta conta não está bloqueada."); return
            try: send(target,"✅ <b>SUA CONTA FOI DESBLOQUEADA</b>\\nVocê já pode voltar a utilizar o PIT PRÊMIOS.")
            except Exception: log.warning("Não foi possível notificar usuário desbloqueado %s",target)
            send(chat,f"✅ Conta <code>{target}</code> desbloqueada. O saldo e todo o histórico continuam preservados.")
        elif cmd=="/admin": send(chat,"🛠️ <b>PAINEL ADMINISTRATIVO PIT</b>\nEscolha uma função abaixo:",admin_menu())
        elif cmd=="/risco":
            if len(p)<2 or not p[1].isdigit():
                send(chat,"Use: /risco ID_DO_INDICADOR"); return
            profile=db.fraud_profile(int(p[1]))
            if not profile:
                send(chat,"Indicador não encontrado."); return
            u=profile["user"]; st=profile["stats"]
            score=profile["risk_score"]; level=profile["risk_level"]
            manual_hold=db.get_referral_manual_hold(int(p[1]))
            score_icon="🔴" if level=="alto" else "🟡" if level=="moderado" else "🟢"
            lines=[f"🛡️ <b>HISTÓRICO ANTIFRAUDE</b>","━━━━━━━━━━━━━━━━━━",f"Indicador: <code>{u['user_id']}</code>",f"Nome: {escape(u['first_name'] or 'Sem nome')} (@{escape(u['username'] or 'sem username')})","",f"{score_icon} <b>PONTUAÇÃO DE RISCO: {score}/100 — {level.upper()}</b>","<i>Indicador de atenção; não comprova fraude nem bloqueia automaticamente.</i>"]
            lines.append("🛡️ Monitoramento manual: "+("ATIVO — "+escape(manual_hold["reason"]) if manual_hold else "inativo"))
            if profile["risk_reasons"]:
                lines.extend(["","⚠️ <b>FATORES QUE AUMENTARAM O RISCO</b>"]+[f"• {escape(reason)}" for reason in profile["risk_reasons"]])
            else:
                lines.append("\nNenhum dos critérios de risco configurados foi atingido.")
            lines.extend(["","📊 <b>RESUMO</b>",f"Indicações totais: <b>{st['total']}</b>",f"Indicações válidas: <b>{st['valid']}</b>",f"Em análise: <b>{st['pending']}</b>",f"Rejeitadas: <b>{st['rejected']}</b>",f"Indicações analisadas: <b>{st['reviewed']}</b>",f"Taxa de rejeição: <b>{(st['rejected']/st['reviewed']):.0%}</b>" if st['reviewed'] else "Taxa de rejeição: sem análises concluídas",f"Cadastros em 2 min: <b>{st['last_2m']}</b>",f"Cadastros em 10 min: <b>{st['last_10m']}</b>",f"Cadastros em 24 horas: <b>{st['last_24h']}</b>",f"Indicações em 7 dias: <b>{st['last_7d']}</b>",f"Indicações em 30 dias: <b>{st['last_30d']}</b>",f"Idade da conta: <b>{st['account_age_hours']:.1f} horas</b>" if st['account_age_hours'] is not None else "Idade da conta: não disponível",f"Alertas nos últimos 30 dias: <b>{st['flagged_30d']}</b>","","🕒 <b>ÚLTIMAS INDICAÇÕES</b>"])
            for item in profile["recent"]:
                state={"approved":"Aprovada","pending":"Pendente","rejected":"Rejeitada"}.get(item["status"],item["status"])
                lines.append(f"• <code>{item['user_id']}</code> — {state} — {item['created_at']}")
                if item["risk_reason"]: lines.append("  ⚠️ "+escape(item["risk_reason"][:140]))
            send(chat,"\n".join(lines),admin_menu())
        elif cmd=="/monitorarindicacoes":
            if len(p)<3 or not p[1].isdigit() or p[2].lower() not in ("on","off"):
                send(chat,"Use: /monitorarindicacoes ID on\nOu: /monitorarindicacoes ID off\n\nON: novas indicações ficam pendentes para revisão. OFF: volta à análise automática."); return
            target=int(p[1]); enabled=p[2].lower()=="on"
            if not db.set_referral_manual_hold(target,enabled,uid):
                send(chat,"Usuário não encontrado."); return
            state="ATIVADO" if enabled else "DESATIVADO"
            detail=("Todas as novas indicações desse usuário ficarão pendentes e não gerarão pontos até aprovação da equipe." if enabled else "As novas indicações voltarão a passar pelos critérios automáticos.")
            send(chat,f"🛡️ <b>MONITORAMENTO MANUAL {state}</b>\nIndicador: <code>{target}</code>\n{detail}\n\nAs indicações antigas e os pontos já registrados não foram alterados.")
        elif cmd=="/usuario":
            if len(p)<2 or not p[1].isdigit(): send(chat,"Use /usuario ID"); return
            target=int(p[1]); details=db.admin_user_details(target)
            if not details: send(chat,"Usuário não encontrado."); return
            u=details["user"]; pending=details["pending"]; totals=details["totals"]
            vip="Ativo" if u["is_vip"] else "Inativo"
            block=db.get_account_block(target)
            block_state=("BLOQUEADA — "+escape(block["reason"])) if block else "LIBERADA"
            block_history=db.account_block_history(target,5)
            lines=[f"👤 <b>FICHA DO MEMBRO</b>","━━━━━━━━━━━━━━━━━━",f"ID: <code>{target}</code>",f"Nome: {escape(u['first_name'] or 'Sem nome')}",f"Username: @{escape(u['username'] or 'não informado')}",f"Saldo: <b>{u['points']:,} pontos</b>",f"Indicações válidas: {u['referrals']}",f"VIP: {vip}",f"Situação da conta: <b>{block_state}</b>",f"Cadastro: {u['created_at']}","","🛡️ <b>ÚLTIMAS AÇÕES DE BLOQUEIO</b>"] 
            if block_history:
                for event in block_history:
                    action="Bloqueada" if event["action"]=="blocked" else "Desbloqueada"
                    lines.append(f"{action} — {event['created_at']} — admin {event['admin_id']}")
            else:
                lines.append("Nenhum bloqueio registrado.")
            lines.extend(["","⏳ <b>PENDÊNCIAS DO USUÁRIO</b>",f"Saques: {pending['pending_payouts']}",f"Pedidos da loja: {pending['pending_reward_orders']}",f"Tarefas: {pending['pending_tasks']}",f"Resgates: {pending['pending_redemptions']}","","📊 <b>HISTÓRICO DE ANÁLISES</b>",f"📋 Tarefas: {totals['tasks_approved']} aprovadas / {totals['tasks_rejected']} rejeitadas",f"🎁 Loja: {totals['rewards_approved']} aprovados / {totals['rewards_rejected']} rejeitados",f"💸 Saques: {totals['payouts_approved']} aprovados / {totals['payouts_rejected']} rejeitados",f"🎟️ Resgates: {totals['redemptions_approved']} aprovados / {totals['redemptions_rejected']} rejeitados","","📜 <b>ÚLTIMAS MOVIMENTAÇÕES</b>"])
            if details["history"]:
                for item in details["history"]:
                    sign="+" if item["amount"]>0 else ""
                    lines.append(f"{sign}{item['amount']} pts — {escape(item['reason'][:55])} ({item['created_at']})")
            else:
                lines.append("Nenhuma movimentação registrada.")
            send(chat,"\n".join(lines),admin_menu())
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
    elif cmd in ("/admin","/stats","/addpoints","/setvip","/pedidos","/saques","/broadcast","/usuario","/novopremio","/bloquear","/desbloquear","/bloqueados","/historicoantifraude","/saude","/auditoria"): pass
    else: send(chat,"Não entendi. Use /start para abrir o menu.")

def callback(c):
    data=c.get("data",""); uid=c.get("from",{}).get("id"); msg=c.get("message",{}); chat=msg.get("chat",{}).get("id")
    try:
        api("answerCallbackQuery",{"callback_query_id":c["id"]})
    except Exception:
        log.warning("Não foi possível confirmar o clique do usuário %s",uid,exc_info=True)
    if chat is None: return
    if uid and not admin(uid):
        block=db.get_account_block(uid)
        if block:
            send(chat,"🚫 <b>CONTA BLOQUEADA</b>\\nMotivo: "+escape(block["reason"])+"\\nEntre em contato com a equipe responsável.")
            return
    navigation_actions={"home","profile","wallet","invite","toprefs","missions","history","help","redeem_info","balance","ranking","daily","vip","help_redeem","tasks","mytasks","notifications","ranking:weekly","ranking:general","shop","myorders","mypayouts","myrefs"}
    if (data in navigation_actions or data.startswith("task:") or data.startswith("history:")) and msg.get("message_id"):
        try: api("deleteMessage",{"chat_id":chat,"message_id":msg["message_id"]})
        except Exception: log.warning("Não foi possível apagar a mensagem anterior do bot")
    if data.startswith("admin:"):
        if not admin(uid): return
        action=data.split(":",1)[1]
        if action=="stats":
            st=db.stats()
            send(chat,f"📊 <b>PAINEL DE ESTATÍSTICAS</b>\n━━━━━━━━━━━━━━━━━━\n👥 Usuários cadastrados: <b>{st['users']:,}</b>\n💰 Pontos em circulação: <b>{st['points']:,}</b>\n\n⏳ <b>ITENS AGUARDANDO A EQUIPE</b>\n🎟️ Resgates: <b>{st['pending_redemptions']}</b>\n💸 Saques Pix: <b>{st['pending_payouts']}</b>\n🎁 Pedidos da loja: <b>{st['pending_reward_orders']}</b>\n📋 Tarefas: <b>{st['pending_tasks']}</b>\n🛡️ Análises antifraude: <b>{st['pending_fraud']}</b>\n\nUse os botões abaixo para abrir cada fila de análise.",admin_menu())
        elif action=="user": send(chat,"👤 Para consultar um membro, envie:\n<code>/usuario ID</code>",admin_menu())
        elif action=="add": send(chat,"➕ Para adicionar ou retirar pontos, envie:\n<code>/addpoints ID QUANTIDADE</code>\nUse quantidade negativa para retirar.",admin_menu())
        elif action=="vip": send(chat,"💎 Para ativar ou desativar o VIP, envie:\n<code>/setvip ID on</code> ou <code>/setvip ID off</code>",admin_menu())
        elif action=="broadcast": send(chat,"📢 Para enviar um comunicado a todos os usuários, envie:\n<code>/broadcast SUA MENSAGEM</code>",admin_menu())
        elif action=="managerewards":
            rows=db.all_rewards()
            if not rows: send(chat,"🗂️ Nenhum prêmio cadastrado.",admin_menu()); return
            kb=[]
            for r in rows:
                state="ATIVO" if r["active"] else "INATIVO"
                stock="∞" if r["stock"]<0 else str(r["stock"])
                label=f"#{r['id']} {r['title'][:18]} — {state} ({stock})"
                if r["active"]: kb.append([btn("🗑️ Desativar "+label,"rewarddisable:"+str(r["id"]))])
                else: kb.append([btn("🔒 "+label,"rewardinfo:"+str(r["id"]))])
            kb.append([btn("⬅️ Voltar ao painel","admin:back")])
            send(chat,"🗂️ <b>GERENCIAR PRÊMIOS</b>\nPrêmios inativos e pedidos antigos permanecem salvos no histórico.",kb)
        elif action=="rewardorders":
            rows=db.pending_reward_orders()
            if not rows: send(chat,"🎁 Nenhum pedido da loja aguardando análise.",admin_menu()); return
            for r in rows:
                kb=[[btn("✅ Aprovar pedido","rewardreview:"+str(r["id"])+":yes"),btn("❌ Rejeitar","rewardreview:"+str(r["id"])+":no")]]
                send(chat,f"🎁 <b>PEDIDO DA LOJA #{r['id']}</b>\nPrêmio: {escape(r['title'])}\nUsuário: <code>{r['user_id']}</code>\nPontos: {r['points_spent']}",kb)
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
            send(chat,"🗂️ <b>GERENCIAR TAREFAS</b>\nEscolha a tarefa que deseja retirar da lista dos usuários:",[[btn("🗑️ #"+str(row["id"])+" — "+row["title"][:30],"taskdisable:"+str(row["id"]))] for row in rows]+[[btn("⬅️ Voltar ao painel","admin:back")]])
        elif action=="back":
            send(chat,"🛠️ <b>PAINEL ADMINISTRATIVO PIT</b>\nEscolha uma função abaixo:",admin_menu())
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
                level="🔴 RISCO ALTO" if r["risk_level"]=="high" else "🟡 REVISÃO"
                send(chat,f"🛡️ <b>ANÁLISE ANTIFRAUDE #{r['id']}</b>\n{level}\n━━━━━━━━━━━━━━━━━━\nIndicador: <code>{r['referrer_id']}</code>\nNovo usuário: <code>{r['referred_user_id']}</code>\nNome: {escape(r['first_name'] or 'Sem nome')} (@{escape(r['username'] or 'sem username')})\n\n📈 <b>Atividade do indicador</b>\nCadastros em 10 min: <b>{r['referrer_last_10m']}</b>\nCadastros em 24 horas: <b>{r['referrer_last_24h']}</b>\nIndicações pendentes: <b>{r['referrer_pending']}</b>\n\n⚠️ <b>Sinais detectados</b>\n{escape(r['risk_reason'])}\n\nA análise é um alerta para revisão humana, não uma confirmação automática de fraude.",kb)
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
    elif data=="mytasks": my_task_submissions(chat,uid)
    elif data=="myrefs": my_referrals(chat,uid)
    elif data=="shop": shop(chat,uid)
    elif data=="myorders": my_reward_orders(chat,uid)
    elif data=="mypayouts": my_payouts(chat,uid)
    elif data.startswith("shopbuy:"):
        try:
            reward_id=int(data.split(":",1)[1])
            order_id=db.create_reward_order(uid,reward_id)
            send(chat,f"✅ Seu pedido da loja foi enviado!\nNúmero: <b>#{order_id}</b>\nOs pontos foram reservados até a análise da equipe.",back())
            for aid in ADMIN_IDS:
                try: send(aid,f"🎁 <b>NOVO PEDIDO DA LOJA #{order_id}</b>\nUsuário: <code>{uid}</code>",[[btn("Revisar pedidos da loja","admin:rewardorders")]])
                except Exception: log.exception("Falha ao avisar admin sobre pedido da loja")
        except (ValueError,IndexError) as e: send(chat,escape(str(e)),back())
    elif data.startswith("task:"):
        try:
            task_id=int(data.split(":")[1])
            task=next((x for x in db.active_tasks_for_user(uid) if x["id"]==task_id),None)
            if not task: send(chat,"Essa tarefa não está mais disponível."); return
            PENDING_TASK_PROOFS[uid]=task_id
            send(chat,f"📋 <b>ENVIAR COMPROVAÇÃO</b>\n━━━━━━━━━━━━━━━━━━\nTarefa: <b>{escape(task['title'])}</b>\nRecompensa: <b>{task['reward_points']:,} pontos</b>\n\nLeia as instruções da tarefa e envie uma comprovação clara, em foto, print ou mensagem.\n\n⚠️ Envie apenas uma comprovação por vez. Enquanto estiver em análise, não será possível enviar outra. Se for rejeitada, você poderá corrigir e reenviar.")
        except (ValueError,IndexError): send(chat,"Tarefa inválida.")
    elif data=="profile": profile(chat,uid)
    elif data=="wallet": balance(chat,uid)
    elif data=="invite": invite(chat,uid)
    elif data=="toprefs": toprefs(chat)
    elif data=="missions": missions(chat,uid)
    elif data=="history": history(chat,uid,0)
    elif data.startswith("history:"):
        try: history(chat,uid,int(data.split(":",1)[1]))
        except (ValueError,IndexError): history(chat,uid,0)
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
        if result.get("blocked_referrer"):
            send(chat,"⛔ O indicador está com a conta bloqueada. A indicação não pode ser aprovada nem gerar pontos enquanto o bloqueio estiver ativo.")
            return
        if result.get("blocked_referred"):
            send(chat,"⛔ O usuário indicado está com a conta bloqueada. A indicação não pode ser aprovada nem gerar pontos enquanto o bloqueio estiver ativo.")
            return
        status="aprovada" if decision=="yes" else "rejeitada"
        api("editMessageText",{"chat_id":chat,"message_id":msg["message_id"],"text":msg.get("text","")+f"\n\nStatus: {status}","parse_mode":"HTML"})
        try:
            if decision=="yes": notify_user(result["referrer_id"],"🎉 Sua indicação foi aprovada na análise de segurança! Os pontos foram creditados na sua carteira.")
            else: notify_user(result["referrer_id"],"⚠️ Uma indicação não foi aprovada na análise de segurança e não gerou pontos.")
        except Exception: log.exception("Falha ao notificar resultado da análise")
    elif data.startswith("payoutcancel:"):
        try:
            payout_id=int(data.split(":",1)[1])
            result=db.cancel_payout_request(uid,payout_id)
            if not result:
                send(chat,"Este saque não está mais pendente ou não pertence à sua conta. Atualize a tela Meus saques.")
            else:
                send(chat,f"✅ <b>Saque #{payout_id} cancelado.</b>\n\nOs {result['points']:,} pontos foram devolvidos à sua carteira.",[[btn("💸 Ver meus saques","mypayouts")],[btn("⬅️ Menu principal","home")]])
        except (ValueError,IndexError):
            send(chat,"Não foi possível cancelar este saque.")
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
    elif data.startswith("rewarddisable:"):
        if not admin(uid): return
        try:
            reward_id=int(data.split(":",1)[1])
            if db.deactivate_reward(reward_id):
                send(chat,f"✅ Prêmio #{reward_id} desativado. O histórico e os pedidos existentes foram preservados.",[[btn("🗂️ Gerenciar prêmios","admin:managerewards")],[btn("⬅️ Painel admin","admin:back")]])
            else:
                send(chat,"Esse prêmio já está inativo ou não existe.",[[btn("🗂️ Gerenciar prêmios","admin:managerewards")]])
        except (ValueError,IndexError): send(chat,"Identificação de prêmio inválida.")
    elif data.startswith("rewardinfo:"):
        if not admin(uid): return
        send(chat,"Este prêmio está inativo. Os registros foram mantidos.",[[btn("🗂️ Gerenciar prêmios","admin:managerewards")]])
    elif data.startswith("rewardcancel:"):
        try:
            order_id=int(data.split(":",1)[1])
            result=db.cancel_reward_order(uid,order_id)
            if not result:
                send(chat,"Este pedido não está mais pendente ou não pertence à sua conta. Atualize a tela Meus pedidos.")
            else:
                send(chat,f"✅ <b>Pedido #{order_id} cancelado.</b>\n\n{result['points_spent']:,} pontos foram devolvidos à sua carteira e o estoque foi restaurado, quando limitado.",[[btn("📦 Ver meus pedidos","myorders")],[btn("⬅️ Menu principal","home")]])
        except (ValueError,IndexError):
            send(chat,"Não foi possível cancelar este pedido.")
    elif data.startswith("rewardreview:"):
        if not admin(uid): return
        _,rid,decision=data.split(":")
        result=db.review_reward_order(int(rid),uid,decision=="yes")
        if not result: send(chat,"Este pedido já foi analisado."); return
        status="aprovado" if decision=="yes" else "rejeitado; os pontos foram devolvidos e o estoque restaurado"
        api("editMessageText",{"chat_id":chat,"message_id":msg["message_id"],"text":msg.get("text","")+f"\n\nStatus: {status}","parse_mode":"HTML"})
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

def process_update(update):
    update_id=update.get("update_id")
    try:
        if update_id is not None and db.update_was_processed(update_id):
            return
        if "message" in update:
            m=update["message"]
            if (m.get("text") or "").startswith("/"):
                command(m)
            elif m.get("chat",{}).get("type")=="private":
                uid=m.get("from",{}).get("id")
                block=db.get_account_block(uid) if uid and not admin(uid) else None
                if block:
                    send(m["chat"]["id"],"🚫 <b>CONTA BLOQUEADA</b>\\nMotivo: "+escape(block["reason"])+"\\nEntre em contato com a equipe responsável.")
                    return
                task_id=PENDING_TASK_PROOFS.pop(uid,None)
                if task_id:
                    try:
                        photo=m.get("photo")
                        proof="photo:"+photo[-1]["file_id"] if photo else (m.get("text") or "").strip()
                        submission_id=db.submit_task(task_id,uid,proof)
                        send(m["chat"]["id"],"✅ <b>COMPROVAÇÃO ENVIADA!</b>\\n\\nSua tarefa foi registrada e está aguardando análise da equipe. Você pode acompanhar o resultado em 📨 Minhas tarefas enviadas.",[[btn("📨 Minhas tarefas enviadas","mytasks")],[btn("⬅️ Menu principal","home")]])
                        for aid in ADMIN_IDS:
                            if proof.startswith("photo:"):
                                api("sendPhoto",{"chat_id":aid,"photo":proof.split(":",1)[1],"caption":f"📋 <b>NOVA COMPROVAÇÃO #{submission_id}</b>\\nUsuário: <code>{uid}</code>\\nTarefa: #{task_id}","parse_mode":"HTML","reply_markup":{"inline_keyboard":[[btn("Revisar tarefas","admin:tasks")]]}})
                            else:
                                send(aid,f"📋 <b>NOVA COMPROVAÇÃO #{submission_id}</b>\\nUsuário: <code>{uid}</code>\\nTarefa: #{task_id}\\nComprovação: {escape(proof[:1000])}",[[btn("Revisar tarefas","admin:tasks")]])
                    except ValueError as e:
                        send(m["chat"]["id"],escape(str(e)))
                else:
                    send(m["chat"]["id"],"Não entendi. Use /start para abrir o menu.")
        elif "callback_query" in update:
            callback(update["callback_query"])
        if update_id is not None:
            db.mark_update_processed(update_id)
    except Exception:
        log.exception("Erro ao processar atualização %s",update.get("update_id"))


from concurrent.futures import ThreadPoolExecutor
from collections import deque
import os

try:
    WORKERS=max(4,min(9,int(os.getenv("BOT_WORKERS","9"))))
except ValueError:
    WORKERS=9
QUEUE_LIMIT=100
UPDATE_POOL=ThreadPoolExecutor(max_workers=WORKERS,thread_name_prefix="pit-update")
UPDATE_CAPACITY=threading.BoundedSemaphore(QUEUE_LIMIT)
USER_QUEUE_LOCK=threading.Lock()
USER_QUEUES={}
ACTIVE_USERS=set()

def update_user_id(update):
    if "message" in update:
        return update["message"].get("from",{}).get("id")
    if "callback_query" in update:
        return update["callback_query"].get("from",{}).get("id")
    return None

def drain_user_queue(uid):
    while True:
        with USER_QUEUE_LOCK:
            pending=USER_QUEUES.get(uid)
            if not pending:
                USER_QUEUES.pop(uid,None)
                ACTIVE_USERS.discard(uid)
                return
            update=pending.popleft()
        try:
            process_update(update)
        except Exception:
            log.exception("Falha inesperada ao processar atualização do usuário %s",uid)
        finally:
            UPDATE_CAPACITY.release()

def schedule_update(update):
    uid=update_user_id(update)
    if uid is None:
        process_update(update)
        return
    if not UPDATE_CAPACITY.acquire(timeout=60):
        log.error("Fila permaneceu cheia por 60 segundos; atualização %s será processada em contenção",update.get("update_id"))
        process_update(update)
        return
    submit_worker=False
    with USER_QUEUE_LOCK:
        pending=USER_QUEUES.setdefault(uid,deque())
        pending.append(update)
        if uid not in ACTIVE_USERS:
            ACTIVE_USERS.add(uid)
            submit_worker=True
    if submit_worker:
        try:
            UPDATE_POOL.submit(drain_user_queue,uid)
        except Exception:
            with USER_QUEUE_LOCK:
                ACTIVE_USERS.discard(uid)
                queued=USER_QUEUES.pop(uid,deque())
            for _ in queued:
                UPDATE_CAPACITY.release()
            raise



def _send_backup_document(chat_id, filename, file_bytes):
    boundary="----PITPREMIOSBackupBoundary"
    body=bytearray()
    crlf=b"\\r\\n"
    fields={"chat_id":str(chat_id),"caption":"🛡️ Backup automático do banco PIT PRÊMIOS. Contém dados pessoais e chaves Pix; mantenha esta conversa privada."}
    for name,value in fields.items():
        body.extend(("--"+boundary).encode()+crlf)
        body.extend(('Content-Disposition: form-data; name="'+name+'"').encode()+crlf+crlf)
        body.extend(value.encode("utf-8")+crlf)
    body.extend(("--"+boundary).encode()+crlf)
    body.extend(('Content-Disposition: form-data; name="document"; filename="'+filename+'"').encode()+crlf)
    body.extend(b"Content-Type: application/zip"+crlf+crlf)
    body.extend(file_bytes+crlf)
    body.extend(("--"+boundary+"--").encode()+crlf)
    req=urllib.request.Request(API+"sendDocument",data=bytes(body),headers={"Content-Type":"multipart/form-data; boundary="+boundary})
    with urllib.request.urlopen(req,timeout=60) as response:
        result=json.loads(response.read())
    if not result.get("ok"): raise RuntimeError(str(result))
    return result.get("result")

def create_and_send_backup():
    if not DATABASE_PATH.exists():
        raise FileNotFoundError("Banco de dados não encontrado; backup não criado.")
    with tempfile.TemporaryDirectory(prefix="pit-premios-backup-") as folder:
        db_copy=os.path.join(folder,"pit_premios.db")
        source=sqlite3.connect(str(DATABASE_PATH),timeout=30)
        target=sqlite3.connect(db_copy)
        try:
            source.backup(target)
            target.commit()
        finally:
            target.close()
            source.close()
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,"w",zipfile.ZIP_DEFLATED) as archive:
            archive.write(db_copy,"pit_premios.db")
        from datetime import datetime
        filename="pit_premios_backup_"+datetime.now().strftime("%Y%m%d_%H%M%S")+".zip"
        payload=buffer.getvalue()
        for admin_id in ADMIN_IDS:
            _send_backup_document(admin_id,filename,payload)
        log.warning("Backup enviado ao(s) administrador(es); tamanho=%s bytes",len(payload))
        return len(payload)

def backup_scheduler():
    while True:
        time.sleep(60)
        try:
            create_and_send_backup()
        except Exception:
            log.exception("Falha ao gerar/enviar backup automático")
        time.sleep(24*60*60)

def health_monitor():
    while True:
        try:
            import resource
            rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            if platform.system()!="Darwin": rss_mb=rss/1024
            else: rss_mb=rss/(1024*1024)
        except Exception:
            rss_mb=-1
        try:
            active=len([t for t in UPDATE_POOL._threads if t.is_alive()]) if "UPDATE_POOL" in globals() else 0
            pending=OUTBOUND_QUEUE.qsize()
            log.warning("Saúde PIT | RAM pico=%.1f MB | trabalhadores=%s/%s | fila_envio=%s",rss_mb,active,WORKERS if "WORKERS" in globals() else 0,pending)
            db.cleanup_processed_updates(14)
        except Exception:
            log.exception("Falha no monitoramento de saúde")
        time.sleep(600)

def main():
    global BOT_USERNAME
    db.init_db()
    me=api("getMe")
    BOT_USERNAME=me.get("username","")
    log.warning("PIT PRÊMIOS iniciado como @%s | trabalhadores=%s | fila=%s",BOT_USERNAME,WORKERS,QUEUE_LIMIT)
    offset=None
    while True:
        try:
            q={"timeout":25,"allowed_updates":["message","callback_query"]}
            if offset is not None:
                q["offset"]=offset
            for update in api("getUpdates",q):
                offset=update["update_id"]+1
                schedule_update(update)
        except KeyboardInterrupt:
            break
        except Exception:
            log.exception("Falha na conexão; nova tentativa em 5 segundos")
            time.sleep(5)

if __name__=="__main__":
    main()
