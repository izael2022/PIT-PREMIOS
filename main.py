import json, logging, time, threading, random, urllib.parse, urllib.request, urllib.error, os, queue, platform
from html import escape
import database as db
from config import BOT_TOKEN, ADMIN_IDS, POINTS_PER_REFERRAL, DAILY_REWARDS, MIN_REDEEM_POINTS, DATABASE_PATH, MONITOR_HEARTBEAT_URL
from backup_utils import create_backup_archive

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
log=logging.getLogger("pit_premios")
API=f"https://api.telegram.org/bot{BOT_TOKEN}/"
BOT_USERNAME=""
BANNER_URL="https://raw.githubusercontent.com/izael2022/PIT-PREMIOS/main/assets/pit_premios_banner.jpg"
LAST_BACKUP_OK=None
LAST_BACKUP_ERROR=""
HEALTH_ALERT_COOLDOWN_MINUTES=30
HEALTH_FALLBACK_LAST={}
HEALTH_FALLBACK_LOCK=threading.Lock()

def _send_health_message(message):
    for admin_id in ADMIN_IDS:
        try:
            api("sendMessage",{"chat_id":admin_id,"text":message,"parse_mode":"HTML"})
        except Exception:
            log.exception("Não foi possível enviar alerta de saúde ao administrador %s",admin_id)

def report_health_issue(alert_key, details):
    message=str(details)[:700]
    log.error("Alerta de saúde [%s]: %s",alert_key,message)
    try:
        should_notify=db.should_notify_health_alert(alert_key,message,HEALTH_ALERT_COOLDOWN_MINUTES)
    except Exception:
        log.exception("Não foi possível persistir alerta de saúde %s; usando controle temporário em memória",alert_key)
        now=time.monotonic()
        with HEALTH_FALLBACK_LOCK:
            previous=HEALTH_FALLBACK_LAST.get(str(alert_key),0)
            should_notify=(now-previous)>=HEALTH_ALERT_COOLDOWN_MINUTES*60
            if should_notify:
                HEALTH_FALLBACK_LAST[str(alert_key)]=now
    if should_notify:
        _send_health_message("🚨 <b>ALERTA DO PIT PRÊMIOS</b>\n\n<b>Problema:</b> "+escape(str(alert_key))+"\n<b>Detalhes:</b> "+escape(message)+"\n\nA equipe deve verificar os logs e a hospedagem.")

def resolve_health_issue(alert_key, details="O serviço voltou a operar normalmente."):
    try:
        if db.resolve_health_alert(alert_key):
            _send_health_message("✅ <b>RECUPERAÇÃO DO PIT PRÊMIOS</b>\n\n<b>Serviço:</b> "+escape(str(alert_key))+"\n"+escape(str(details)))
    except Exception:
        log.exception("Não foi possível registrar recuperação de saúde %s",alert_key)

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
BACKGROUND_THREADS={}
BACKGROUND_THREADS_LOCK=threading.Lock()
BACKGROUND_RESTART_AT={}
BACKGROUND_FAILURES={}

def ensure_background_worker(name,target,restart_backoff=5):
    """Start a worker once, or restart it after an unexpected thread exit."""
    now=time.monotonic()
    should_alert=False
    with BACKGROUND_THREADS_LOCK:
        current=BACKGROUND_THREADS.get(name)
        if current is not None and current.is_alive():
            return current
        if current is not None:
            allowed_at=BACKGROUND_RESTART_AT.get(name,0)
            if now<allowed_at:
                return None
            failures=BACKGROUND_FAILURES.get(name,0)+1
            BACKGROUND_FAILURES[name]=failures
            delay=0 if float(restart_backoff)<=0 else min(60, max(float(restart_backoff), 2 ** min(failures,6)))
            BACKGROUND_RESTART_AT[name]=now+delay
            should_alert=True
        worker=threading.Thread(target=target,name=name,daemon=True)
        BACKGROUND_THREADS[name]=worker
        worker.start()
    if should_alert:
        report_health_issue("worker_"+name,f"O serviço interno {name} parou inesperadamente e foi iniciado novamente.")
    return worker

def ensure_background_workers():
    workers=(
        ("pit-outbound",_outbound_worker),
        ("pit-backup",backup_scheduler),
        ("pit-health",health_monitor),
    )
    for name,target in workers:
        ensure_background_worker(name,target)



def _outbound_worker():
    last_chat={}
    last_global=0.0
    while not OUTBOUND_STOP.is_set():
        try:
            item=OUTBOUND_QUEUE.get(timeout=1)
        except queue.Empty:
            continue
        chat,text_value,keyboard,future=item
        try:
            wait=max(0,1.05-(time.monotonic()-last_chat.get(str(chat),0)))
            if wait: time.sleep(wait)
            global_wait=max(0,0.04-(time.monotonic()-last_global))
            if global_wait: time.sleep(global_wait)
            payload={"chat_id":chat,"text":text_value,"parse_mode":"HTML"}
            if keyboard: payload["reply_markup"]={"inline_keyboard":keyboard}
            result=api("sendMessage",payload)
            last_chat[str(chat)]=time.monotonic()
            last_global=time.monotonic()
            future.set_result(result)
        except Exception as exc:
            future.set_exception(exc)
            log.exception("Falha no envio para chat %s",chat)
        finally:
            OUTBOUND_QUEUE.task_done()

def start_outbound_worker():
    global OUTBOUND_READY
    worker=ensure_background_worker("pit-outbound",_outbound_worker)
    OUTBOUND_READY=bool(worker and worker.is_alive())
    return worker

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
        text=str(message)
        category="geral"; title="Aviso do PIT PRÊMIOS"
        low=text.lower()
        if "saque" in low or "pix" in low: category="financeiro"; title="Atualização de saque/Pix"
        elif "indica" in low or "convid" in low: category="indicacoes"; title="Atualização de indicação"
        elif "tarefa" in low: category="tarefas"; title="Atualização de tarefa"
        elif "resgate" in low or "pedido" in low: category="resgates"; title="Atualização de resgate"
        db.record_notification(uid,category,title,text)
        if db.notifications_enabled(uid):
            send(uid,text)
    except Exception:
        log.exception("Falha ao registrar/enviar notificação ao usuário %s",uid)

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
    return [
        [btn("👤 MEU PERFIL","profile"),btn("💰 MINHA CARTEIRA","wallet")],
        [btn("🎯 MISSÕES E TAREFAS","missions"),btn("🎁 CHECK-IN DIÁRIO","daily")],
        [btn("🎁 BAÚ SURPRESA","game:chest"),btn("🎡 ROLETA DE PONTOS","game:roulette")],
        [btn("🎟️ RASPADINHA VIRTUAL","game:scratch")],
        [btn("🚀 CONVIDAR AMIGOS","invite"),btn("🏆 RANKING","ranking")],
        [btn("🎁 LOJA DE PRÊMIOS","shop"),btn("🎟️ RESGATAR PONTOS","redeem_info")],
        [btn("💎 CLUBE VIP","vip"),btn("👥 MEUS CONVIDADOS","myrefs")],
        [btn("📦 MEUS PEDIDOS","myorders"),btn("💸 MEUS SAQUES","mypayouts")],
        [btn("🔐 MINHA CHAVE PIX","pixprofile")],
        [btn("📋 TAREFAS DISPONÍVEIS","tasks"),btn("📨 MINHAS TAREFAS","mytasks")],
        [btn("📜 EXTRATO","history"),btn("🔔 NOTIFICAÇÕES","notifications")],
        [btn("❓ CENTRAL DE AJUDA","help")]
    ]
def back(): return [[btn("⬅️ Menu principal","home")]]

def admin_menu():
    return [[btn("📊 Estatísticas","admin:stats"),btn("👤 Consultar usuário","admin:user")],
            [btn("🆔 IDs de todos os usuários","admin:userids:0")],
            [btn("➕ Adicionar pontos","admin:add"),btn("💎 Gerenciar VIP","admin:vip")],
            [btn("🎟️ Resgates","admin:orders"),btn("💸 Saques Pix","admin:payouts")],
            [btn("🎁 Pedidos da loja","admin:rewardorders")],
            [btn("🗂️ Gerenciar prêmios","admin:managerewards")],
            [btn("🛡️ Análise antifraude","admin:fraud")],
            [btn("📋 Revisar tarefas","admin:tasks"),btn("🗂️ Gerenciar tarefas","admin:manage_tasks")],
            [btn("📢 Enviar comunicado","admin:broadcast")],
            [btn("💹 Painel financeiro","admin:finance")],
            [btn("🩺 Monitoramento do bot","admin:health")],
            [btn("⬅️ Fechar painel","home")]]

def admin_health_report(chat):
    try:
        snapshot=db.health_snapshot()
        stats=db.stats()
        active_alerts=db.active_health_alerts(10)
        history=db.recent_health_alerts(5)
        last_backup=db.get_health_metric("last_backup_ok")
        try:
            import resource
            peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            ram_mb=peak/(1024*1024 if platform.system()=="Darwin" else 1024)
            ram_label=f"{ram_mb:.1f} MB (pico)"
        except Exception:
            ram_label="indisponível neste sistema"
        runtime=update_runtime_snapshot()
        workers=runtime["in_flight"]
        integrity=str(snapshot.get("database_integrity") or "desconhecida")
        integrity_label="✅ íntegro" if integrity.lower()=="ok" else "⚠️ "+escape(integrity)
        backup_label=escape(last_backup["metric_value"][:40]) if last_backup else "Ainda não registrado"
        backup_updated=escape(last_backup["updated_at"][:19]) if last_backup else "—"
        heartbeat_label="✅ configurado" if MONITOR_HEARTBEAT_URL else "⚠️ não configurado"
        backup_state="⚠️ sem backup registrado" if not last_backup else "✅ registro disponível"
        if last_backup:
            try:
                from datetime import datetime, timezone
                stamp=datetime.strptime(last_backup["metric_value"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                age_hours=(datetime.now(timezone.utc)-stamp).total_seconds()/3600
                backup_state=("🚨 ATRASADO" if age_hours>30 else "✅ recente")+f" ({age_hours:.1f} h)"
            except (ValueError, TypeError):
                backup_state="⚠️ data do backup inválida"
        lines=[
            "🩺 <b>MONITORAMENTO DO PIT PRÊMIOS</b>",
            "━━━━━━━━━━━━━━━━━━",
            "🟢 Processo: <b>respondendo</b>",
            f"💾 RAM: <b>{ram_label}</b>",
            f"🧵 Trabalhadores ocupados: <b>{workers}/{runtime['workers_created']}</b>",
            f"📨 Atualizações aguardando: <b>{runtime['queued']}</b>",
            f"👤 Usuários com fila ativa: <b>{runtime['active_users']}</b>",
            f"📊 Processadas desde o início: <b>{runtime['completed']:,}</b> | falhas: <b>{runtime['failed']:,}</b>",
            f"⚙️ Serviços internos ativos: <b>{sum(1 for thread in BACKGROUND_THREADS.values() if thread.is_alive())}/3</b>",
            f"👥 Usuários cadastrados: <b>{stats['users']:,}</b>",
            f"🪙 Pontos em circulação: <b>{stats['points']:,}</b>",
            f"📥 Atualizações pendentes: <b>{snapshot['pending_updates']}</b>",
            f"📤 Fila de envio: <b>{OUTBOUND_QUEUE.qsize()}</b>",
            f"🗄️ SQLite: <b>{integrity_label}</b>",
            f"🚨 Alertas ativos: <b>{len(active_alerts)}</b>",
            f"💾 Último backup: <b>{backup_label}</b> — {backup_state}",
            f"🕒 Registro do backup: <b>{backup_updated}</b>",
            f"🌐 Heartbeat externo: <b>{heartbeat_label}</b>",
            "",
            "<b>Alertas recentes</b>"
        ]
        if history:
            for item in history:
                icon="🔴" if item["status"]=="active" else "✅"
                lines.append(f"{icon} <b>{escape(item['alert_key'])}</b> — {escape(item['status'])}\n<i>{escape((item['details'] or '')[:180])}</i>\n<i>{escape(item['last_seen_at'] or '')}</i>")
        else:
            lines.append("Nenhum incidente registrado.")
        lines.extend(["","<i>O estado online significa que o processo respondeu a esta consulta. RAM é o pico reportado pelo sistema. Este painel não substitui monitor externo da hospedagem.</i>"])
        send(chat,"\n".join(lines),[[btn("🔄 Atualizar monitoramento","admin:health")],[btn("⬅️ Voltar ao painel","admin:back")]])
    except Exception:
        log.exception("Falha ao montar painel de saúde")
        send(chat,"⚠️ Não foi possível carregar todos os indicadores. Verifique os logs e tente novamente.",[[btn("🔄 Tentar novamente","admin:health")],[btn("⬅️ Voltar ao painel","admin:back")]])


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
    u=db.get_user(uid); points=int(u["points"] if u else 0)
    minimum=int(MIN_REDEEM_POINTS)
    remaining=max(0,minimum-points)
    status="✅ Você já atingiu o mínimo para solicitar." if remaining==0 else f"Faltam <b>{remaining:,} pontos</b> para atingir o mínimo."
    send(chat,f"💰 <b>MINHA CARTEIRA</b>\n━━━━━━━━━━━━━━━━━━\n🪙 Saldo disponível: <b>{points:,} pontos</b>\n💵 Valor equivalente: <b>R$ {points/100:.2f}</b>\n\n📌 <b>CONVERSÃO</b>\n100 pontos = R$ 1,00\n💸 Mínimo para saque: <b>{minimum:,} pontos (R$ {minimum/100:.2f})</b>\n{status}\n\n🔐 Ao solicitar um saque, os pontos ficam reservados enquanto a equipe analisa. Se o pedido for rejeitado ou cancelado, eles retornam à carteira.\n\nPara solicitar, cadastre e tenha sua chave Pix aprovada em <b>Minha chave Pix</b>. Depois use <code>/sacar PONTOS</code>.\n\nAcompanhe entradas e saídas no seu <b>Extrato</b>.",[[btn("📜 Ver meu extrato","history")],[btn("💸 Meus saques","mypayouts")],[btn("⬅️ Menu principal","home")]])

def ranking(chat):
    rows=db.ranking()
    lines=["🏆 <b>RANKING GERAL PIT PRÊMIOS</b>","<i>Classificação por pontos acumulados.</i>","━━━━━━━━━━━━━━━━━━"]
    medals={1:"🥇",2:"🥈",3:"🥉"}
    if not rows:
        lines.append("Ainda não há participantes no ranking. Seja o primeiro a acumular pontos!")
    for i,u in enumerate(rows,1):
        name=escape((u["first_name"] or ("@"+u["username"] if u["username"] else str(u["user_id"])))[:35])
        mark=medals.get(i,f"<b>{i}º</b>")
        lines.append(f"{mark} <b>{name}</b>\n   💰 {int(u['points']):,} pontos")
    lines.extend(["","🎯 <i>Acumule pontos nas missões, check-ins e indicações válidas para subir no ranking.</i>"])
    send(chat,"\n".join(lines),[[btn("📅 Ver ranking semanal","ranking:weekly")],[btn("🔄 Atualizar ranking geral","ranking:general")],[btn("⬅️ Voltar às opções","ranking")],[btn("🏠 Menu principal","home")]])


def ranking_menu(chat):
    send(chat,"🏆 <b>RANKING PIT PRÊMIOS</b>\n━━━━━━━━━━━━━━━━━━\nVeja quem está na liderança!\n\n📅 <b>Semanal:</b> pontos conquistados nos últimos 7 dias.\n🏆 <b>Geral:</b> total de pontos acumulados na conta.\n\nOs três primeiros recebem destaque com medalhas.",[[btn("📅 Ranking semanal","ranking:weekly")],[btn("🏆 Ranking geral","ranking:general")],[btn("⬅️ Menu principal","home")]])

def weekly_ranking(chat):
    rows=db.weekly_ranking()
    lines=["📅 <b>RANKING SEMANAL PIT PRÊMIOS</b>","<i>Pontos ganhos nos últimos 7 dias.</i>","━━━━━━━━━━━━━━━━━━"]
    medals={1:"🥇",2:"🥈",3:"🥉"}
    if not rows:
        lines.append("Ainda não há pontos registrados nos últimos 7 dias. Participe das missões e atividades para aparecer aqui!")
    for i,u in enumerate(rows,1):
        name=escape((u["first_name"] or ("@"+u["username"] if u["username"] else str(u["user_id"])))[:35])
        mark=medals.get(i,f"<b>{i}º</b>")
        lines.append(f"{mark} <b>{name}</b>\n   ⭐ {int(u['points']):,} pontos")
    lines.extend(["","🔥 <i>O ranking é atualizado conforme os pontos são registrados.</i>"])
    send(chat,"\n".join(lines),[[btn("🏆 Ver ranking geral","ranking:general")],[btn("🔄 Atualizar ranking semanal","ranking:weekly")],[btn("⬅️ Voltar às opções","ranking")],[btn("🏠 Menu principal","home")]])

def daily(chat,uid):
    ok,streak,earned=db.daily_claim(uid,DAILY_REWARDS)
    if ok:
        day=(streak-1)%len(DAILY_REWARDS)+1
        next_day=day%len(DAILY_REWARDS)+1
        send(chat,f"🎉 <b>CHECK-IN CONFIRMADO!</b>\nVocê recebeu <b>+{earned} pontos</b>!\n🔥 Sequência atual: <b>{streak} dias</b>\n📅 Dia da recompensa: <b>{day}/{len(DAILY_REWARDS)}</b>\n\n<i>Volte amanhã para ganhar a recompensa do dia {next_day}!</i>",back())
    else:
        send(chat,f"⏳ <b>Check-in já realizado!</b>\nSua sequência atual é de <b>{streak} dias</b>. Volte amanhã.",back())

def profile(chat,uid):
    p=db.get_profile(uid)
    name=escape((p.get("first_name") or "Participante")[:40])
    points=int(p.get("points",0) or 0)
    referrals=int(p.get("referrals",0) or 0)
    streak=int(p.get("daily_streak",0) or 0)
    is_vip=bool(p.get("is_vip",0))
    expiry=p.get("vip_expires_at")
    if is_vip:
        vip="ATIVO 💎"
        vip_detail=("Válido até: <b>"+escape(str(expiry))+"</b>") if expiry else "Acesso VIP permanente"
    else:
        vip="MEMBRO"
        vip_detail="Complete as metas de indicação para conquistar VIP"
    daily_done=p.get("last_daily")==db.today()
    daily_state="✅ Realizado hoje" if daily_done else "🎁 Disponível agora"
    next_goal=next((n for n in (1,5,10) if referrals<n),None)
    goal_line=(f"Próxima meta: <b>{next_goal} indicações</b> — faltam <b>{next_goal-referrals}</b>" if next_goal else "🏆 Todas as metas de indicação foram alcançadas!")
    member_since=str(p.get("created_at") or "")[:10] or "—"
    text_value=(
        f"👤 <b>MEU PERFIL PIT PRÊMIOS</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Olá, <b>{name}</b>! 🐾\n\n"
        f"💰 <b>SALDO E CONQUISTAS</b>\n"
        f"Saldo: <b>{points:,} pontos</b>\n"
        f"Equivalente: <b>R$ {points/100:.2f}</b>\n"
        f"👥 Indicações válidas: <b>{referrals}</b>\n"
        f"📈 {goal_line}\n\n"
        f"💎 <b>CLUBE VIP</b>\n"
        f"Categoria: <b>{vip}</b>\n{vip_detail}\n\n"
        f"🔥 Sequência de check-in: <b>{streak} dia(s)</b>\n"
        f"🎁 Check-in: <b>{daily_state}</b>\n"
        f"📅 Membro desde: <b>{member_since}</b>\n"
        f"🆔 ID: <code>{uid}</code>"
    )
    keyboard=[
        [btn("💰 Abrir carteira","wallet"),btn("🚀 Convidar amigos","invite")],
        [btn("🎯 Ver minhas missões","missions"),btn("💎 Clube VIP","vip")],
        [btn("📜 Meu extrato","history")],
        [btn("⬅️ Menu principal","home")]
    ]
    send(chat,text_value,keyboard)
def invite(chat,uid):
    p=db.get_profile(uid); link=f"https://t.me/{BOT_USERNAME}?start={uid}"
    keyboard=[[{"text":"📤 Compartilhar meu convite","url":"https://t.me/share/url?url="+urllib.parse.quote(link,safe="")+"&text="+urllib.parse.quote("Entre no PIT PRÊMIOS pelo meu convite e participe para ganhar pontos e prêmios!",safe="")}],[btn("👥 Ver meus convidados","myrefs")],[btn("🏆 Top indicadores","toprefs")],[btn("🎯 Ver missões e metas","missions")],[btn("⬅️ Menu principal","home")]]
    send(chat,f"🚀 <b>CONVIDE E GANHE</b>\n━━━━━━━━━━━━━━━━━━\nEste é o seu link pessoal. Compartilhe com amigos e convide-os para conhecer o PIT PRÊMIOS!\n\n🔗 <b>SEU LINK</b>\n<code>{link}</code>\n\n🎁 Recompensa por indicação válida: <b>{POINTS_PER_REFERRAL:,} pontos</b>\n👥 Indicações válidas: <b>{p['referrals']}</b>\n\n<b>Como funciona?</b>\n1. Compartilhe seu link.\n2. Seu amigo abre o link e inicia o bot.\n3. A indicação aparece em Meus convidados.\n4. Após validação, os pontos são creditados.\n\n⚠️ Apenas novos usuários são contabilizados. Indicações suspeitas podem passar por análise antifraude.",keyboard)
def my_referrals(chat,uid):
    rows=db.user_referrals(uid,15)
    p=db.get_profile(uid)
    total=int(p.get("referrals",0) or 0)
    pending=sum(1 for r in rows if r["referral_status"]=="pending")
    rejected=sum(1 for r in rows if r["referral_status"]=="rejected")
    lines=["👥 <b>MEUS CONVIDADOS</b>","━━━━━━━━━━━━━━━━━━",f"✅ Indicações válidas: <b>{total}</b>",f"⏳ Em análise nesta lista: <b>{pending}</b>",f"❌ Não aprovadas nesta lista: <b>{rejected}</b>",""]
    if not rows:
        lines.append("Você ainda não possui convidados registrados. Compartilhe seu link para começar!")
    labels={"pending":"⏳ Em análise","approved":"✅ Válida","rejected":"❌ Não aprovada"}
    for r in rows:
        name=escape((r["first_name"] or "Participante")[:35])
        username="@"+escape(r["username"]) if r["username"] else "sem username"
        status=labels.get(r["referral_status"],"Status não identificado")
        lines.append(f"\n<b>{name}</b> ({username})\nID: <code>{r['user_id']}</code>\nStatus: {status}\nCadastro: {escape(str(r['created_at']))}")
    lines.append("\n<i>Exibindo até os 15 convidados mais recentes. Os totais válidos consideram seu cadastro completo.</i>")
    send(chat,"\n".join(lines),[[btn("🚀 Compartilhar meu link","invite")],[btn("🎯 Ver metas e bônus","missions")],[btn("⬅️ Menu principal","home")]])

def toprefs(chat):
    rows=db.top_referrals(); lines=["🚀 <b>CAMPEÕES DE INDICAÇÃO</b>","━━━━━━━━━━━━━━━━━━"]
    for i,r in enumerate(rows,1): lines.append(f"{i}. <b>{escape((r['first_name'] or str(r['user_id']))[:24])}</b> — {r['referrals']} amigos")
    if not rows: lines.append("As primeiras indicações ainda estão por vir.")
    send(chat,"\n".join(lines),back())
def missions(chat,uid):
    p=db.get_profile(uid)
    referrals=int(p.get("referrals",0) or 0)
    checked=p.get("last_daily")==db.today()
    milestones=db.referral_milestone_status(uid)
    vip_goals=db.referral_vip_status(uid)
    lines=["🎯 <b>MISSÕES E CONQUISTAS</b>","━━━━━━━━━━━━━━━━━━",f"🎁 <b>Check-in diário:</b> {'✅ Concluído hoje' if checked else '🟢 Disponível'}",f"🔥 <b>Sua sequência:</b> {int(p.get('daily_streak',0) or 0)} dia(s)",f"👥 <b>Indicações válidas:</b> {referrals}","", "🏆 <b>METAS DE INDICAÇÃO</b>"]
    kb=[[btn("🎁 Fazer check-in diário","daily"),btn("🚀 Convidar amigos","invite")]]
    if not milestones: lines.append("Nenhuma meta de indicação configurada no momento.")
    for item in milestones:
        target=int(item["milestone"]); progress=min(100,int(referrals*100/target)) if target else 0
        status="🎉 Bônus disponível para resgate" if item["reached"] and not item["claimed"] else ("✅ Bônus já recebido" if item["claimed"] else f"🔒 Progresso: {min(referrals,target)}/{target} ({progress}%)")
        lines.append(f"\n<b>{target} indicações</b> — prêmio: <b>{item['bonus']:,} pontos</b>\n{status}")
        if item["reached"] and not item["claimed"]: kb.append([btn(f"🎉 Resgatar bônus de {target}","milestone:"+str(target))])
    lines.extend(["","💎 <b>METAS DO CLUBE VIP</b>"])
    if not vip_goals: lines.append("Consulte a equipe para conhecer as metas VIP.")
    for item in vip_goals:
        target=int(item["milestone"]); progress=min(100,int(referrals*100/target)) if target else 0
        status="🎉 VIP disponível para resgate" if item["reached"] and not item["claimed"] else ("✅ VIP resgatado" if item["claimed"] else f"🔒 Progresso: {min(referrals,target)}/{target} ({progress}%)")
        lines.append(f"\n<b>{target} amigos</b> — VIP por <b>{item['days']} dias</b>\n{status}")
        if item["reached"] and not item["claimed"]: kb.append([btn(f"💎 Resgatar VIP ({item['days']} dias)","vipmilestone:"+str(target))])
    lines.extend(["","💡 <i>As recompensas de indicação dependem de novos cadastros válidos. Indicações em análise só contam após aprovação.</i>"])
    kb.extend([[btn("📋 Ver tarefas disponíveis","tasks"),btn("📨 Minhas tarefas","mytasks")],[btn("⬅️ Menu principal","home")]])
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
    profile_data=db.get_profile(uid)
    points=int(profile_data.get("points",0) or 0)
    lines=[
        "🎁 <b>LOJA DE PRÊMIOS PIT</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"💰 Sua carteira: <b>{points:,} pontos</b>",
        "",
        "Troque seus pontos por prêmios disponíveis.",
        "Escolha um item abaixo para solicitar:"
    ]
    if not rows:
        lines.extend(["","📭 <b>Nenhum prêmio disponível no momento.</b>","Volte mais tarde para conferir as novidades!"])
        send(chat,"\n".join(lines),[[btn("📦 Meus pedidos","myorders")],[btn("⬅️ Menu principal","home")]])
        return
    kb=[]
    for r in rows:
        cost=int(r["points_cost"])
        stock="♾️ Estoque ilimitado" if r["stock"]<0 else f"📦 {r['stock']} unidade(s) disponível(is)"
        affordable=points>=cost
        state="✅ Você tem pontos suficientes" if affordable else f"🔒 Faltam {cost-points:,} pontos"
        lines.append(
            f"\n🎁 <b>{escape(r['title'])}</b>\n"
            f"{escape(r['description'])}\n"
            f"💎 Preço: <b>{cost:,} pontos</b>\n"
            f"{stock}\n"
            f"{state}"
        )
        label=f"🎁 Solicitar {r['title'][:20]} ({cost:,} pts)"
        kb.append([btn(label,"shopbuy:"+str(r["id"]))])
    lines.extend(["","ℹ️ Ao solicitar, os pontos ficam reservados até a equipe analisar o pedido.","Se o pedido for rejeitado ou cancelado, os pontos são devolvidos."])
    kb.extend([
        [btn("📦 Acompanhar meus pedidos","myorders")],
        [btn("💰 Minha carteira","wallet"),btn("📜 Meu extrato","history")],
        [btn("⬅️ Menu principal","home")]
    ])
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
    rows=db.notification_history(uid,8)
    history="\n".join(f"• <b>{escape(str(x['title']))}</b> — {escape(str(x['created_at']))}\n{escape(str(x['message']))[:180]}" for x in rows) or "Nenhum aviso registrado ainda."
    send(chat,f"🔔 <b>CENTRAL DE NOTIFICAÇÕES</b>\nStatus: <b>{state}</b>\n\n<b>Últimos avisos</b>\n{history}",[[btn(label,action)],[btn("🔄 Atualizar","notifications")],[btn("⬅️ Menu principal","home")]])

def help_page(chat):
    send(chat,f"❓ <b>CENTRAL DE AJUDA PIT PRÊMIOS</b>\n━━━━━━━━━━━━━━━━━━\n<b>💰 Pontos e carteira</b>\nConfira seu saldo em Minha carteira e consulte o Extrato para ver créditos e débitos. A conversão exibida é de 100 pontos = R$ 1,00.\n\n<b>🚀 Convites</b>\nUse seu link exclusivo em Convidar amigos. Somente novos cadastros pelo seu link podem contar como indicação. Algumas indicações passam por análise antifraude.\n\n<b>🎯 Missões</b>\nFaça o check-in diário, complete metas de indicação e acompanhe tarefas disponíveis. Leia as regras de cada tarefa antes de enviar a comprovação.\n\n<b>🎁 Prêmios e resgates</b>\nConsulte a Loja de prêmios para fazer pedidos. Para solicitar resgate de pontos, use <code>/resgatar PONTOS DESCRIÇÃO</code>. Mínimo configurado: <b>{MIN_REDEEM_POINTS:,} pontos</b>.\n\n<b>💸 Saques</b>\nCadastre sua chave em <b>Minha chave Pix</b> e aguarde a aprovação da equipe. Depois use <code>/sacar PONTOS</code>. Os pagamentos são realizados manualmente.\n\n<b>💎 Clube VIP</b>\nConsulte as metas em Missões ou fale com a administração.\n\n<b>🛟 Precisa de ajuda?</b>\nEnvie uma mensagem para a equipe responsável pelo grupo oficial. Nunca compartilhe senha ou códigos de acesso.",[[btn("💰 Minha carteira","wallet"),btn("🎯 Missões","missions")],[btn("🚀 Convidar amigos","invite")],[btn("⬅️ Menu principal","home")]])

def _valid_pix_key(key_type,key):
    value=str(key or "").strip()
    kind=str(key_type or "").strip().upper()
    if not value or len(value)>200:
        return False
    digits="".join(ch for ch in value if ch.isdigit())
    if kind=="CPF":
        if len(digits)!=11 or len(set(digits))==1: return False
        nums=[int(x) for x in digits]
        first=(sum(nums[i]*(10-i) for i in range(9))*10)%11
        first=0 if first==10 else first
        second=(sum(nums[i]*(11-i) for i in range(10))*10)%11
        second=0 if second==10 else second
        return nums[9]==first and nums[10]==second
    if kind=="CNPJ":
        if len(digits)!=14 or len(set(digits))==1: return False
        nums=[int(x) for x in digits]
        def digit(part,weights):
            value=sum(a*b for a,b in zip(part,weights))%11
            return 0 if value<2 else 11-value
        return nums[12]==digit(nums[:12],[5,4,3,2,9,8,7,6,5,4,3,2]) and nums[13]==digit(nums[:13],[6,5,4,3,2,9,8,7,6,5,4,3,2])
    if kind=="EMAIL":
        import re
        return len(value)<=254 and re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+",value) is not None
    if kind=="TELEFONE":
        import re
        if re.fullmatch(r"\+?[0-9().\-\s]+",value) is None:
            return False
        if len(digits) in (10,11):
            return True
        return len(digits) in (12,13) and digits.startswith("55")
    if kind=="ALEATORIA":
        import re
        return re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}",value) is not None
    return False



def _masked_pix(value):
    value=str(value or "")
    if len(value)<=6: return "••••"
    return value[:2]+"••••"+value[-2:]


def pix_profile_page(chat,uid):
    profile=db.get_pix_profile(uid)
    if not profile:
        send(chat,"🔐 <b>CADASTRO DA CHAVE PIX</b>\n\nCadastre uma chave que esteja em seu nome. A equipe fará a conferência manual antes de aprovar.\n\nEscolha o tipo:",[[btn("CPF","pix:type:CPF"),btn("CNPJ","pix:type:CNPJ")],[btn("E-mail","pix:type:EMAIL"),btn("Telefone","pix:type:TELEFONE")],[btn("Chave aleatória","pix:type:ALEATORIA")],[btn("⬅️ Menu principal","home")]])
        return
    status={"pending":"⏳ Aguardando conferência","approved":"✅ Aprovada pela equipe","rejected":"❌ Reprovada — cadastre novamente"}.get(profile["status"],profile["status"])
    send(chat,f"🔐 <b>MINHA CHAVE PIX</b>\n\nTipo: <b>{escape(profile['pix_key_type'])}</b>\nChave: <code>{escape(_masked_pix(profile['pix_key']))}</code>\nTitular informado: <b>{escape(profile['owner_name'])}</b>\nStatus: <b>{status}</b>\n\nA validação é administrativa; o bot não consulta automaticamente o DICT nem confirma a titularidade no Mercado Pago.",[[btn("🔄 Alterar chave Pix","pix:change")],[btn("⬅️ Menu principal","home")]])


def command(m,update_id=None):
    t=m.get("text") or ""; p=t.split(maxsplit=2); cmd=p[0].split("@")[0].lower()
    chat=m["chat"]["id"]; uid=m.get("from",{}).get("id")
    if m.get("chat",{}).get("type")!="private":
        if cmd=="/start":
            send(chat,"🐾 Para participar do PIT PRÊMIOS e consultar sua carteira com segurança, abra uma conversa privada com o bot: https://t.me/"+(BOT_USERNAME or "PIT_PREMIOS_BOT"))
        else:
            send(chat,"🔒 Por segurança, os comandos do PIT PRÊMIOS só podem ser usados na conversa privada com o bot.")
        return
    if uid and not admin(uid):
        block=db.get_account_block(uid)
        if block:
            send(chat,"🚫 <b>CONTA BLOQUEADA</b>\n\nSeu acesso ao PIT PRÊMIOS está temporariamente bloqueado.\nMotivo: "+escape(block["reason"])+"\n\nSe acredita que houve um engano, entre em contato com a equipe responsável.")
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
        args=t.split(maxsplit=1)
        if len(args)<2 or not args[1].isdigit(): send(chat,"Use: /sacar PONTOS"); return
        pts=int(args[1]); profile=db.get_pix_profile(uid)
        if not profile or profile["status"]!="approved":
            send(chat,"🔐 Você precisa cadastrar uma chave Pix e aguardar a aprovação da equipe antes de solicitar um saque.",[[btn("Cadastrar chave Pix","pixprofile")],[btn("⬅️ Menu principal","home")]]); return
        pix_key=profile["pix_key"]; key_type=profile["pix_key_type"]
        if not _valid_pix_key(key_type,pix_key):
            send(chat,"❌ Sua chave cadastrada não passou na validação de formato. Atualize o cadastro em Minha chave Pix."); return
        try: rid=db.create_payout_request(uid,pts,pix_key,key_type,MIN_REDEEM_POINTS,update_id=update_id)
        except ValueError as e: send(chat,escape(str(e))); return
        amount=pts/100
        send(chat,f"✅ Solicitação de saque <b>#{rid}</b> enviada!\nValor: <b>R$ {amount:.2f}</b>\nSeus pontos ficaram reservados até a análise da equipe.")
        for aid in ADMIN_IDS:
            try: send(aid,f"💸 <b>NOVO PEDIDO DE SAQUE #{rid}</b>\nUsuário: <code>{uid}</code>\nPontos: {pts}\nValor: R$ {amount:.2f}\nChave ({escape(key_type)}): <code>{escape(pix_key)}</code>\n\n⚠️ Faça a transferência Pix primeiro. Depois confirme abaixo.",[[btn("✅ Confirmar Pix pago","payout:"+str(rid)+":yes"),btn("❌ Rejeitar pedido","payout:"+str(rid)+":no")]])
            except Exception: log.exception("Falha ao notificar admin sobre saque")
    elif cmd=="/resgatar":
        if len(p)<3 or not p[1].isdigit(): send(chat,"Use /resgatar PONTOS DESCRIÇÃO"); return
        pts=int(p[1]); reward=p[2].strip()
        if pts<MIN_REDEEM_POINTS or pts>10000000 or not reward or len(reward)>500:
            send(chat,f"Informe uma descrição de até 500 caracteres e pelo menos {MIN_REDEEM_POINTS:,} pontos."); return
        try: rid=db.create_redemption(uid,pts,reward,update_id=update_id)
        except ValueError as e: send(chat,escape(str(e))); return
        send(chat,f"✅ Pedido #{rid} enviado. Os pontos ficam reservados até análise.")
        for aid in ADMIN_IDS:
            try: send(aid,f"Novo resgate #{rid}\nUsuário: {uid}\nPontos: {pts}\nPrêmio: {escape(reward)}")
            except Exception: log.exception("Falha ao notificar admin")
    elif cmd in ("/admin","/stats","/addpoints","/setvip","/pedidos","/saques","/broadcast","/usuario","/novopremio","/risco","/monitorarindicacoes","/bloquear","/desbloquear","/bloqueados","/historicoantifraude","/saude","/health","/auditoria") and admin(uid):
        if cmd in ("/saude","/health"):
            admin_health_report(chat)
        elif cmd=="/auditoria":
            rows=db.recent_admin_audit(20)
            lines=["🧾 <b>ÚLTIMAS AÇÕES ADMINISTRATIVAS</b>"]
            for row in rows: lines.append(f"\n{row['created_at']} — admin <code>{row['admin_id']}</code>\n{escape(row['action'])}: {escape(row['details'])}")
            send(chat,"\n".join(lines) if rows else "Ainda não há ações administrativas registradas.")
        elif cmd=="/bloquear":
            if len(p)<3 or not p[1].isdigit() or not p[2].strip():
                send(chat,"Use: /bloquear ID MOTIVO"); return
            target=int(p[1])
            if target in ADMIN_IDS:
                send(chat,"⛔ Por segurança, não é permitido bloquear uma conta de administrador."); return
            reason=t.split(maxsplit=2)[2]
            if not db.block_account(target,uid,reason):
                send(chat,"Usuário não encontrado no banco de dados."); return
            try: send(target,"🚫 <b>SUA CONTA FOI BLOQUEADA</b>\nMotivo: "+escape(reason)+"\nEntre em contato com a equipe se precisar contestar.")
            except Exception: log.warning("Não foi possível notificar usuário bloqueado %s",target)
            send(chat,f"✅ Conta <code>{target}</code> bloqueada. Cadastro, saldo e histórico foram preservados.")
        elif cmd=="/bloqueados":
            rows=db.list_blocked_accounts(30)
            if not rows:
                send(chat,"🛡️ Não há contas bloqueadas no momento."); return
            lines=["🚫 <b>CONTAS BLOQUEADAS</b>","━━━━━━━━━━━━━━━━━━"]
            for row in rows:
                name=escape(row["first_name"] or "Sem nome")
                lines.append(f"\n<b>{name}</b> — <code>{row['user_id']}</code>\nMotivo: {escape(row['reason'])}\nBloqueada em: {row['blocked_at']}\nPor admin: <code>{row['blocked_by']}</code>")
            send(chat,"\n".join(lines),admin_menu())
        elif cmd=="/historicoantifraude":
            if len(p)<2 or not p[1].isdigit():
                send(chat,"Use: /historicoantifraude ID"); return
            target=int(p[1]); rows=db.account_block_history(target)
            if not rows:
                send(chat,"Não há histórico de bloqueios para esse usuário."); return
            lines=[f"🧾 <b>HISTÓRICO DE BLOQUEIO</b>\nUsuário: <code>{target}</code>","━━━━━━━━━━━━━━━━━━"]
            for row in rows:
                action="🔒 BLOQUEADO" if row["action"]=="blocked" else "🔓 DESBLOQUEADO"
                lines.append(f"\n{action} — {row['created_at']}\nAdmin: <code>{row['admin_id']}</code>\nMotivo: {escape(row['reason'] or 'Não informado')}")
            send(chat,"\n".join(lines),admin_menu())
        elif cmd=="/desbloquear":
            if len(p)<2 or not p[1].isdigit():
                send(chat,"Use: /desbloquear ID"); return
            target=int(p[1])
            if target in ADMIN_IDS:
                send(chat,"⛔ Administradores não podem ser alterados por este comando."); return
            if not db.unblock_account(target,uid):
                send(chat,"Esta conta não está bloqueada."); return
            try: send(target,"✅ <b>SUA CONTA FOI DESBLOQUEADA</b>\nVocê já pode voltar a utilizar o PIT PRÊMIOS.")
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
            s=db.stats()
            send(
                chat,
                "📊 <b>ESTATÍSTICAS DO PIT PRÊMIOS</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"👥 Usuários cadastrados: <b>{s['users']:,}</b>\n"
                f"💰 Pontos em circulação: <b>{s['points']:,}</b>\n\n"
                "⏳ <b>PENDÊNCIAS PARA ANÁLISE</b>\n"
                f"🎟️ Resgates: <b>{s['pending_redemptions']}</b>\n"
                f"💸 Saques Pix: <b>{s['pending_payouts']}</b>\n"
                f"🎁 Pedidos da loja: <b>{s['pending_reward_orders']}</b>\n"
                f"📋 Tarefas: <b>{s['pending_tasks']}</b>\n"
                f"🛡️ Análises antifraude: <b>{s['pending_fraud']}</b>"
            )
        elif cmd=="/addpoints":
            if len(p)<3 or not p[1].isdigit() or not p[2].lstrip("-").isdigit(): send(chat,"Use /addpoints ID QUANTIDADE"); return
            amount=int(p[2])
            if not amount or abs(amount)>1000000: send(chat,"Quantidade inválida."); return
            try: db.add_points(int(p[1]),amount,f"Ajuste por admin {uid}",update_id=update_id)
            except ValueError as e: send(chat,escape(str(e))); return
            send(chat,"✅ Saldo atualizado.")
        elif cmd=="/setvip":
            if len(p)<3 or not p[1].isdigit() or p[2].lower() not in ("on","off"): send(chat,"Use /setvip ID on|off"); return
            if not db.set_vip(int(p[1]),p[2].lower()=="on"):
                send(chat,"Usuário não encontrado."); return
            send(chat,"✅ VIP atualizado.")
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
    elif cmd in ("/admin","/stats","/addpoints","/setvip","/pedidos","/saques","/broadcast","/usuario","/novopremio","/bloquear","/desbloquear","/bloqueados","/historicoantifraude","/saude","/health","/auditoria"): pass
    else: send(chat,"Não entendi. Use /start para abrir o menu.")

def _should_delete_callback_message(data,uid):
    """Remove telas temporárias ao navegar, sem apagar comprovantes ou decisões."""
    if data.startswith("admin:"):
        return admin(uid)
    navigation_actions={"home","profile","wallet","invite","toprefs","missions","history","help","redeem_info","balance","ranking","daily","vip","help_redeem","tasks","mytasks","notifications","ranking:weekly","ranking:general","shop","myorders","mypayouts","myrefs"}
    return data in navigation_actions or data.startswith("task:") or data.startswith("history:")


def send_admin_user_ids(chat,page=0):
    page_size=30
    total,ids=db.admin_user_ids_page(page,page_size)
    pages=max(1,(total+page_size-1)//page_size)
    page=max(0,min(int(page),pages-1))
    if not ids:
        send(chat,"🆔 <b>IDs dos usuários</b>\nNenhum usuário cadastrado.",admin_menu())
        return
    first=page*page_size+1
    last=first+len(ids)-1
    body="\n".join(f"<code>{user_id}</code>" for user_id in ids)
    message=(f"🆔 <b>IDs DE TODOS OS USUÁRIOS</b>\n"
             f"Total cadastrado: <b>{total}</b>\n"
             f"Página <b>{page+1}/{pages}</b> — exibindo <b>{first}–{last}</b>\n"
             f"━━━━━━━━━━━━━━━━━━\n{body}")
    keyboard=[]
    navigation=[]
    if page>0:
        navigation.append(btn("⬅️ Anterior",f"admin:userids:{page-1}"))
    if page+1<pages:
        navigation.append(btn("Próxima ➡️",f"admin:userids:{page+1}"))
    if navigation:
        keyboard.append(navigation)
    keyboard.append([btn("⬅️ Voltar ao painel","admin:back")])
    send(chat,message,keyboard)


def callback(c,update_id=None):
    data=c.get("data",""); uid=c.get("from",{}).get("id"); msg=c.get("message",{}); chat=msg.get("chat",{}).get("id")
    if chat is None: return
    if msg.get("chat",{}).get("type")!="private":
        try: api("answerCallbackQuery",{"callback_query_id":c["id"],"text":"Por segurança, abra o bot no privado.","show_alert":True})
        except Exception: log.warning("Falha ao bloquear callback em grupo",exc_info=True)
        return
    if uid and not admin(uid):
        block=db.get_account_block(uid)
        if block:
            try:
                api("answerCallbackQuery",{"callback_query_id":c["id"],"text":"Sua conta está bloqueada. Procure a equipe de atendimento.","show_alert":True})
            except Exception:
                log.warning("Não foi possível exibir o aviso de bloqueio ao usuário %s",uid,exc_info=True)
            return
    try:
        api("answerCallbackQuery",{"callback_query_id":c["id"]})
    except Exception:
        log.warning("Não foi possível confirmar o clique do usuário %s",uid,exc_info=True)
    if admin(uid) and any(data.startswith(prefix) for prefix in ("taskreview:","refreview:","payout:","rewardreview:","review:","rewarddisable:")):
        try: db.log_admin_action(uid,"callback",data)
        except Exception: log.exception("Falha ao registrar auditoria de callback")
    if _should_delete_callback_message(data,uid) and msg.get("message_id"):
        try: api("deleteMessage",{"chat_id":chat,"message_id":msg["message_id"]})
        except Exception: log.warning("Não foi possível apagar a mensagem anterior do bot")
    if data.startswith("admin:"):
        if not admin(uid): return
        action=data.split(":",1)[1]
        if action=="stats":
            st=db.stats()
            send(chat,f"📊 <b>PAINEL DE ESTATÍSTICAS</b>\n━━━━━━━━━━━━━━━━━━\n👥 Usuários cadastrados: <b>{st['users']:,}</b>\n💰 Pontos em circulação: <b>{st['points']:,}</b>\n\n⏳ <b>ITENS AGUARDANDO A EQUIPE</b>\n🎟️ Resgates: <b>{st['pending_redemptions']}</b>\n💸 Saques Pix: <b>{st['pending_payouts']}</b>\n🎁 Pedidos da loja: <b>{st['pending_reward_orders']}</b>\n📋 Tarefas: <b>{st['pending_tasks']}</b>\n🛡️ Análises antifraude: <b>{st['pending_fraud']}</b>\n\nUse os botões abaixo para abrir cada fila de análise.",admin_menu())
        elif action=="health":
            admin_health_report(chat)
        elif action=="finance":
            f=db.financial_dashboard()
            send(chat,f"💹 <b>PAINEL FINANCEIRO</b>\n━━━━━━━━━━━━━━━━━━\n🪙 Pontos creditados (histórico): <b>{f['points_issued']:,}</b>\n🪙 Pontos debitados (histórico): <b>{f['points_debited']:,}</b>\n🔒 Pontos reservados em saques pendentes: <b>{f['points_reserved']:,}</b>\n\n💸 Pix pagos e aprovados: <b>R$ {f['pix_paid_cents']/100:.2f}</b>\n⏳ Pix aguardando análise: <b>R$ {f['pix_pending_cents']/100:.2f}</b>\n↩️ Pontos de saques rejeitados: <b>{f['rejected_payout_points']:,}</b>\n\n🎟️ Resgates aprovados: <b>{f['approved_redemptions']:,}</b> pontos\n🎁 Loja aprovada: <b>{f['approved_store_points']:,}</b> pontos\n🎮 Pontos ganhos nos jogos: <b>{f['game_points']:,}</b>\n\n📚 <b>CONCILIAÇÃO DA CARTEIRA</b>\nSaldo atual dos usuários: <b>{f['wallet_balance_points']:,}</b>\nSaldo líquido do extrato: <b>{f['ledger_net_points']:,}</b>\nDiferença: <b>{f['ledger_difference']:,}</b>\nStatus: <b>{'✅ conciliado' if f['ledger_reconciled'] else '⚠️ requer conferência'}</b>\n\n⏳ Resgates pendentes: <b>{f['pending_redemption_points']:,}</b> pontos\n🎁 Pedidos da loja pendentes: <b>{f['pending_store_points']:,}</b> pontos\n\n<i>Pontos são créditos virtuais; somente Pix aprovado representa pagamento confirmado. Diferenças históricas devem ser investigadas antes de qualquer ajuste.</i>",admin_menu())
        elif action=="userids" or action.startswith("userids:"):
            page=int(action.split(":",1)[1]) if ":" in action else 0
            send_admin_user_ids(chat,page)
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
    if data.startswith("pixreview:"):
        if not admin(uid): return
        _,target,decision=data.split(":")
        result=db.review_pix_profile(int(target),uid,decision=="yes")
        if not result: send(chat,"Esse cadastro Pix não está mais aguardando análise."); return
        status="aprovada" if decision=="yes" else "reprovada"
        api("editMessageText",{"chat_id":chat,"message_id":msg["message_id"],"text":msg.get("text","")+f"\\n\\nStatus: {status}","parse_mode":"HTML"})
        notify_user(int(target),f"Sua chave Pix foi {status} pela equipe. "+("Você já pode solicitar saques." if decision=="yes" else "Acesse Minha chave Pix para cadastrar novamente."))
    elif data=="pixprofile":
        pix_profile_page(chat,uid)
    elif data=="pix:change":
        send(chat,"Escolha o tipo da nova chave Pix:",[[btn("CPF","pix:type:CPF"),btn("CNPJ","pix:type:CNPJ")],[btn("E-mail","pix:type:EMAIL"),btn("Telefone","pix:type:TELEFONE")],[btn("Chave aleatória","pix:type:ALEATORIA")]])
    elif data.startswith("pix:type:"):
        key_type=data.split(":",2)[2]
        if key_type not in ("CPF","CNPJ","EMAIL","TELEFONE","ALEATORIA"): return
        db.set_pix_setup_step(uid,"key",key_type)
        send(chat,f"Envie agora sua chave Pix do tipo <b>{escape(key_type)}</b> em uma única mensagem.\\n\\nNão envie senha, código ou token bancário.")
    elif data=="notifications":
        notifications_page(chat,uid)
    elif data=="notifications:on":
        db.set_notifications(uid,True); notifications_page(chat,uid)
    elif data=="notifications:off":
        db.set_notifications(uid,False); notifications_page(chat,uid)
    elif data.startswith("game:"):
        game=data.split(":",1)[1]
        configs={
            "chest":("🎁 BAÚ SURPRESA DIÁRIO",[0,2,3,5,8,10,15,20],[25,25,20,15,8,4,2,1]),
            "roulette":("🎡 ROLETA DE PONTOS",[0,2,5,8,10,15,20,30],[25,20,18,14,10,7,4,2]),
            "scratch":("🎟️ RASPADINHA VIRTUAL",[0,2,3,5,8,10,15,25],[25,22,18,14,10,6,4,1])
        }
        if game not in configs: return
        title,prizes,weights=configs[game]
        if game in db.game_status(uid):
            send(chat,f"⏳ Você já participou de {title.lower()} hoje. Volte amanhã!",back()); return
        prize=random.choices(prizes,weights=weights,k=1)[0]
        try:
            db.play_daily_game(uid,game,prize)
            send(chat,f"{title}\n━━━━━━━━━━━━━━━━━━\n🎉 Resultado: <b>+{prize} pontos</b>!\n\nCada jogo tem uma tentativa por dia. Seus pontos já foram adicionados à carteira.",[[btn("🎁 Baú surpresa","game:chest"),btn("🎡 Roleta","game:roulette")],[btn("🎟️ Raspadinha","game:scratch")],[btn("💰 Minha carteira","wallet")],[btn("⬅️ Menu principal","home")]])
        except ValueError as e:
            send(chat,escape(str(e)),back())
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
            order_id=db.create_reward_order(uid,reward_id,update_id=update_id)
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
            db.set_pending_task_proof(uid,task_id)
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
        _,rid,decision=data.split(":"); result=db.review_referral(int(rid),uid,decision=="yes",POINTS_PER_REFERRAL)
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
            if decision=="yes":
                message=("🎉 Sua indicação foi aprovada na análise de segurança! Os pontos foram creditados na sua carteira." if POINTS_PER_REFERRAL>0 else "✅ Sua indicação foi aprovada na análise de segurança. No momento, a recompensa em pontos está desativada.")
                notify_user(result["referrer_id"],message)
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
            db.mark_update_processed(update_id)
            return True
        if "message" in update:
            m=update["message"]
            if (m.get("text") or "").startswith("/"):
                command(m,update_id=update_id)
            elif m.get("chat",{}).get("type")=="private":
                uid=m.get("from",{}).get("id")
                block=db.get_account_block(uid) if uid and not admin(uid) else None
                if block:
                    send(m["chat"]["id"],"🚫 <b>CONTA BLOQUEADA</b>\nMotivo: "+escape(block["reason"])+"\nEntre em contato com a equipe responsável.")
                    if update_id is not None: db.mark_update_processed(update_id)
                    return True
                pix_step=db.get_pix_setup_step(uid)
                if pix_step:
                    value=(m.get("text") or "").strip()
                    if not value:
                        send(m["chat"]["id"],"Envie os dados em texto para continuar.")
                    elif pix_step["step"]=="key":
                        if not _valid_pix_key(pix_step["key_type"],value):
                            send(m["chat"]["id"],"❌ O formato da chave não corresponde ao tipo escolhido. Tente novamente.")
                        else:
                            db.set_pix_setup_step(uid,"owner",pix_step["key_type"],value)
                            send(m["chat"]["id"],"Agora informe o nome completo do titular da chave Pix, exatamente como aparece no banco.")
                    elif pix_step["step"]=="owner":
                        if len(value)<3 or len(value)>120 or any(ch.isdigit() for ch in value):
                            send(m["chat"]["id"],"Informe o nome completo do titular (3 a 120 caracteres, sem números).")
                        else:
                            db.save_pix_profile(uid,pix_step["key_type"],pix_step["pix_key"],value)
                            db.clear_pix_setup_step(uid)
                            send(m["chat"]["id"],"✅ Cadastro recebido! Sua chave Pix ficará aguardando conferência manual da equipe. Você será avisado quando houver uma decisão.",[[btn("Ver minha chave Pix","pixprofile")],[btn("⬅️ Menu principal","home")]])
                            profile=db.get_pix_profile(uid)
                            for aid in ADMIN_IDS:
                                try:
                                    send(aid,f"🔐 <b>NOVA CHAVE PIX PARA CONFERÊNCIA</b>\\nUsuário: <code>{uid}</code>\\nTipo: {escape(profile['pix_key_type'])}\\nChave: <code>{escape(profile['pix_key'])}</code>\\nTitular informado: {escape(profile['owner_name'])}\\n\\nConfira manualmente e decida:",[[btn("✅ Aprovar chave","pixreview:"+str(uid)+":yes"),btn("❌ Reprovar","pixreview:"+str(uid)+":no")]])
                                except Exception: log.exception("Falha ao notificar admin sobre cadastro Pix")
                else:
                    task_id=db.get_pending_task_proof(uid)
                    if task_id:
                        try:
                            photo=m.get("photo")
                            proof="photo:"+photo[-1]["file_id"] if photo else (m.get("text") or "").strip()
                            submission_id=db.submit_task(task_id,uid,proof)
                            db.clear_pending_task_proof(uid)
                            send(m["chat"]["id"],"✅ <b>COMPROVAÇÃO ENVIADA!</b>\\n\\nSua tarefa foi registrada e está aguardando análise da equipe. Você pode acompanhar o resultado em 📨 Minhas tarefas enviadas.",[[btn("📨 Minhas tarefas enviadas","mytasks")],[btn("⬅️ Menu principal","home")]])
                            for aid in ADMIN_IDS:
                                if proof.startswith("photo:"):
                                    api("sendPhoto",{"chat_id":aid,"photo":proof.split(":",1)[1],"caption":f"📋 <b>NOVA COMPROVAÇÃO #{submission_id}</b>\\nUsuário: <code>{uid}</code>\\nTarefa: #{task_id}","parse_mode":"HTML","reply_markup":{"inline_keyboard":[[btn("Revisar tarefas","admin:tasks")]]}})
                                else:
                                    send(aid,f"📋 <b>NOVA COMPROVAÇÃO #{submission_id}</b>\\nUsuário: <code>{uid}</code>\\nTarefa: #{task_id}\\nComprovação: {escape(proof[:1000])}",[[btn("Revisar tarefas","admin:tasks")]])
                        except ValueError as e:
                            if str(e)!="Envie a comprovação solicitada.":
                                db.clear_pending_task_proof(uid)
                            send(m["chat"]["id"],escape(str(e)))
                    else:
                        send(m["chat"]["id"],"Não entendi. Use /start para abrir o menu.")
        elif "callback_query" in update:
            callback(update["callback_query"],update_id=update_id)
        if update_id is not None:
            db.mark_update_processed(update_id)
    except Exception:
        log.exception("Erro ao processar atualização %s; ela permanecerá pendente para nova tentativa.",update.get("update_id"))
        raise
    return True


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
UPDATE_METRICS_LOCK=threading.Lock()
UPDATE_IN_FLIGHT=0
UPDATE_COMPLETED_TOTAL=0
UPDATE_FAILED_TOTAL=0

def update_runtime_snapshot():
    with USER_QUEUE_LOCK:
        queued=sum(len(items) for items in USER_QUEUES.values())
        active_users=len(ACTIVE_USERS)
    with UPDATE_METRICS_LOCK:
        in_flight=UPDATE_IN_FLIGHT
        completed=UPDATE_COMPLETED_TOTAL
        failed=UPDATE_FAILED_TOTAL
    created=sum(1 for worker in UPDATE_POOL._threads if worker.is_alive()) if "UPDATE_POOL" in globals() else 0
    return {"workers_created":created,"in_flight":in_flight,"queued":queued,"active_users":active_users,
            "completed":completed,"failed":failed,"capacity":QUEUE_LIMIT if "QUEUE_LIMIT" in globals() else 0}

def update_user_id(update):
    if "message" in update:
        return update["message"].get("from",{}).get("id")
    if "callback_query" in update:
        return update["callback_query"].get("from",{}).get("id")
    return None

def drain_user_queue(uid):
    global UPDATE_IN_FLIGHT, UPDATE_COMPLETED_TOTAL, UPDATE_FAILED_TOTAL
    while True:
        with USER_QUEUE_LOCK:
            pending=USER_QUEUES.get(uid)
            if not pending:
                USER_QUEUES.pop(uid,None)
                ACTIVE_USERS.discard(uid)
                return
            update=pending.popleft()
        with UPDATE_METRICS_LOCK:
            UPDATE_IN_FLIGHT+=1
        succeeded=False
        try:
            for attempt in range(3):
                try:
                    succeeded=process_update(update) is True
                    if succeeded: break
                except Exception:
                    if attempt==2:
                        log.exception("Atualização %s falhou após 3 tentativas; permanecerá na fila durável.",update.get("update_id"))
                    else:
                        delay=min(30,2**attempt)
                        log.warning("Nova tentativa %s/3 para atualização %s em %s segundos.",attempt+2,update.get("update_id"),delay,exc_info=True)
                        time.sleep(delay)
        finally:
            with UPDATE_METRICS_LOCK:
                UPDATE_IN_FLIGHT-=1
                if succeeded:
                    UPDATE_COMPLETED_TOTAL+=1
                else:
                    UPDATE_FAILED_TOTAL+=1
            UPDATE_CAPACITY.release()

def schedule_update(update):
    uid=update_user_id(update)
    if uid is None:
        process_update(update)
        return
    # Aplicar backpressure em vez de processar fora da fila por usuário.
    # Isso preserva a ordem das atualizações quando a fila está cheia.
    UPDATE_CAPACITY.acquire()
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
    crlf=b"\r\n"
    fields={"chat_id":str(chat_id),"caption":"🛡️ Backup automático do banco PIT PRÊMIOS. Contém dados pessoais e chaves Pix; mantenha esta conversa privada."}
    for name,value in fields.items():
        body.extend(("--"+boundary).encode()+crlf)
        body.extend(('Content-Disposition: form-data; name="'+name+'"').encode()+crlf+crlf)
        body.extend(value.encode("utf-8")+crlf)
    body.extend(("--"+boundary).encode()+crlf)
    body.extend(('Content-Disposition: form-data; name="document"; filename="'+filename+'"').encode()+crlf)
    body.extend(b"Content-Type: application/octet-stream"+crlf+crlf)
    body.extend(file_bytes+crlf)
    body.extend(("--"+boundary+"--").encode()+crlf)
    req=urllib.request.Request(API+"sendDocument",data=bytes(body),headers={"Content-Type":"multipart/form-data; boundary="+boundary})
    with urllib.request.urlopen(req,timeout=60) as response:
        result=json.loads(response.read())
    if not result.get("ok"): raise RuntimeError(str(result))
    return result.get("result")

def create_and_send_backup():
    payload=create_backup_archive(DATABASE_PATH)
    from datetime import datetime
    filename="pit_premios_backup_"+datetime.now().strftime("%Y%m%d_%H%M%S")+".pitbackup"
    sent=0
    for admin_id in ADMIN_IDS:
        try:
            _send_backup_document(admin_id,filename,payload)
            sent+=1
        except Exception:
            log.exception("Falha ao enviar backup ao administrador %s",admin_id)
    if not sent:
        raise RuntimeError("Backup criado e validado, mas não foi enviado a nenhum administrador.")
    log.warning("Backup validado e enviado a %s administrador(es); tamanho=%s bytes",sent,len(payload))
    return len(payload)

def backup_retry_delay(consecutive_failures):
    """Intervalos de retry: 5 min, 15 min, 1 h e no máximo 6 h."""
    failures=max(1,int(consecutive_failures))
    return (300,900,3600,21600)[min(failures-1,3)]


def backup_scheduler():
    global LAST_BACKUP_OK,LAST_BACKUP_ERROR
    consecutive_failures=0
    time.sleep(60)
    while True:
        try:
            create_and_send_backup()
            LAST_BACKUP_OK=time.time()
            LAST_BACKUP_ERROR=""
            consecutive_failures=0
            try: db.set_health_metric("last_backup_ok",time.strftime("%Y-%m-%d %H:%M:%S",time.localtime(LAST_BACKUP_OK)))
            except Exception: log.exception("Não foi possível persistir a data do último backup")
            resolve_health_issue("backup","Um backup criptografado foi criado, validado e enviado.")
            time.sleep(24*60*60)
        except Exception as exc:
            consecutive_failures+=1
            LAST_BACKUP_ERROR=str(exc)[:700]
            retry_delay=backup_retry_delay(consecutive_failures)
            log.exception("Falha ao gerar/enviar backup automático; nova tentativa em %s segundos (falha %s).",retry_delay,consecutive_failures)
            report_health_issue("backup",LAST_BACKUP_ERROR)
            time.sleep(retry_delay)

def send_external_heartbeat():
    """Ping a configured HTTPS heartbeat only after a successful health cycle."""
    url=str(MONITOR_HEARTBEAT_URL or "").strip()
    if not url:
        return False
    parsed=urllib.parse.urlparse(url)
    if parsed.scheme!="https" or not parsed.netloc:
        raise ValueError("MONITOR_HEARTBEAT_URL deve ser uma URL HTTPS válida.")
    request=urllib.request.Request(url,headers={"User-Agent":"PIT-PREMIOS-Health/1.0"})
    with urllib.request.urlopen(request,timeout=10) as response:
        status=getattr(response,"status",None)
        if status is None:
            status=response.getcode()
        if not 200<=int(status)<300:
            raise RuntimeError(f"Monitor externo respondeu HTTP {status}.")
    return True

def health_monitor():
    while True:
        try:
            import resource
            from datetime import datetime
            rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            if platform.system()!="Darwin": rss_mb=rss/1024
            else: rss_mb=rss/(1024*1024)
        except Exception:
            rss_mb=-1
        try:
            runtime=update_runtime_snapshot()
            outbound=OUTBOUND_QUEUE.qsize()
            queued_updates=runtime["queued"]
            log.warning("Saúde PIT | RAM pico=%.1f MB | ocupados=%s/%s | fila_updates=%s/%s | usuarios_ativos=%s | concluidas=%s | falhas=%s | fila_envio=%s",
                        rss_mb,runtime["in_flight"],runtime["workers_created"],queued_updates,runtime["capacity"],
                        runtime["active_users"],runtime["completed"],runtime["failed"],outbound)
            try:
                snapshot=db.health_snapshot()
            except Exception as exc:
                report_health_issue("database","Não foi possível consultar o SQLite: "+str(exc))
                raise
            resolve_health_issue("database","O banco SQLite voltou a responder.")
            if snapshot["database_integrity"]!="ok":
                report_health_issue("database_integrity","PRAGMA quick_check retornou: "+str(snapshot["database_integrity"]))
            else:
                resolve_health_issue("database_integrity","A verificação rápida do SQLite voltou a passar.")
            if snapshot["pending_updates"]>=250:
                report_health_issue("update_backlog",f"Existem {snapshot['pending_updates']} atualizações pendentes na fila durável.")
            else:
                resolve_health_issue("update_backlog","A fila durável de atualizações está sob controle.")
            if queued_updates>=80:
                report_health_issue("update_queue_pressure",f"Há {queued_updates} atualizações aguardando processamento.")
            else:
                resolve_health_issue("update_queue_pressure","A fila de processamento voltou ao nível normal.")
            if outbound>=400:
                report_health_issue("outbound_queue_pressure",f"A fila de envio do Telegram está com {outbound} mensagens.")
            else:
                resolve_health_issue("outbound_queue_pressure","A fila de envio do Telegram voltou ao nível normal.")
            if LAST_BACKUP_ERROR:
                report_health_issue("backup",LAST_BACKUP_ERROR)
            last_backup_metric=db.get_health_metric("last_backup_ok")
            if last_backup_metric:
                try:
                    from datetime import datetime, timezone
                    stamp=datetime.strptime(last_backup_metric["metric_value"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                    backup_age=(datetime.now(timezone.utc)-stamp).total_seconds()
                    if backup_age>30*60*60:
                        report_health_issue("backup_stale",f"Último backup registrado há {backup_age/3600:.1f} horas.")
                    else:
                        resolve_health_issue("backup_stale","O último backup está dentro da janela esperada.")
                except (ValueError, TypeError):
                    report_health_issue("backup_stale","A data do último backup não pôde ser interpretada.")
            else:
                report_health_issue("backup_stale","Ainda não existe registro de backup bem-sucedido.")
            db.cleanup_processed_updates(14)
            if MONITOR_HEARTBEAT_URL:
                try:
                    send_external_heartbeat()
                    resolve_health_issue("external_heartbeat_delivery","O sinal de vida foi enviado ao monitor externo.")
                except Exception as heartbeat_exc:
                    log.exception("Falha ao enviar heartbeat ao monitor externo")
                    report_health_issue("external_heartbeat_delivery",str(heartbeat_exc))
        except Exception as exc:
            log.exception("Falha no monitoramento de saúde")
            report_health_issue("health_monitor",str(exc))
        time.sleep(60)

def telegram_reconnect_delay(consecutive_failures):
    """Progressive backoff for Telegram polling failures, capped at one minute."""
    failures=max(1,int(consecutive_failures))
    return min(60,5*(2**min(failures-1,4)))


def telegram_get_me_with_retry():
    """Authenticate on startup and keep retrying while Telegram is unavailable."""
    failures=0
    while True:
        try:
            return api("getMe")
        except Exception as exc:
            failures+=1
            delay=telegram_reconnect_delay(failures)
            log.exception("Telegram indisponível durante inicialização; nova tentativa em %s segundos.",delay)
            report_health_issue("telegram_startup",str(exc))
            time.sleep(delay)


def main():
    global BOT_USERNAME
    db.init_db()
    start_outbound_worker()
    # Recupera todos os lotes pendentes antes de buscar novas atualizações.
    last_pending_id=0
    while True:
        pending_batch=db.pending_updates(limit=500,after_update_id=last_pending_id)
        if not pending_batch:
            break
        for pending_update in pending_batch:
            schedule_update(pending_update)
            last_pending_id=max(last_pending_id,int(pending_update["update_id"]))
        if len(pending_batch)<500:
            break
    ensure_background_workers()
    me=telegram_get_me_with_retry()
    BOT_USERNAME=me.get("username","")
    resolve_health_issue("telegram_startup","O bot autenticou-se na API do Telegram.")
    log.warning("PIT PRÊMIOS iniciado como @%s | trabalhadores=%s | fila=%s",BOT_USERNAME,WORKERS,QUEUE_LIMIT)
    offset=None
    consecutive_connection_failures=0
    while True:
        try:
            ensure_background_workers()
            start_outbound_worker()
            q={"timeout":25,"allowed_updates":["message","callback_query"]}
            if offset is not None:
                q["offset"]=offset
            updates=api("getUpdates",q)
            if consecutive_connection_failures:
                log.warning("Conexão com a API do Telegram restabelecida após %s falha(s) consecutiva(s).",consecutive_connection_failures)
            consecutive_connection_failures=0
            resolve_health_issue("telegram_api","A conexão com a API do Telegram foi restabelecida.")
            for update in updates:
                # Persistir antes de avançar o offset confirma recebimento sem perder
                # atualizações caso o processo reinicie durante o processamento.
                db.enqueue_update(update)
                schedule_update(update)
                offset=update["update_id"]+1
        except KeyboardInterrupt:
            break
        except Exception as exc:
            consecutive_connection_failures+=1
            retry_delay=telegram_reconnect_delay(consecutive_connection_failures)
            log.exception("Falha na conexão com o Telegram; nova tentativa em %s segundos (falha consecutiva %s).",retry_delay,consecutive_connection_failures)
            report_health_issue("telegram_api",str(exc))
            time.sleep(retry_delay)

if __name__=="__main__":
    main()

# deep-audit branch marker
