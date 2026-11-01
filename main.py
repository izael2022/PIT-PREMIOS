import json, logging, time, urllib.parse, urllib.request, urllib.error
from html import escape
import database as db
from config import BOT_TOKEN, ADMIN_IDS, POINTS_PER_REFERRAL, DAILY_REWARD, MIN_REDEEM_POINTS

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
log=logging.getLogger("pit_premios")
API=f"https://api.telegram.org/bot{BOT_TOKEN}/"
BOT_USERNAME=""
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
        for name,value in fields.items():
            body.extend(("--"+boundary+"\\r\\n").encode())
            body.extend(('Content-Disposition: form-data; name="'+name+'"\\r\\n\\r\\n').encode())
            body.extend(str(value).encode("utf-8")); body.extend(b"\\r\\n")
        body.extend(("--"+boundary+"\\r\\n").encode())
        body.extend(b'Content-Disposition: form-data; name="photo"; filename="pit_premios_banner.jpg"\\r\\n')
        body.extend(b"Content-Type: image/jpeg\\r\\n\\r\\n")
        body.extend(BANNER_BYTES); body.extend(b"\\r\\n")
        body.extend(("--"+boundary+"--\\r\\n").encode())
        req=urllib.request.Request(API+"sendPhoto",data=bytes(body),headers={"Content-Type":"multipart/form-data; boundary="+boundary})
        with urllib.request.urlopen(req,timeout=40) as response:
            result=json.loads(response.read())
        if not result.get("ok"):
            raise RuntimeError(str(result))
        return result.get("result")
    except Exception:
        log.exception("Não foi possível enviar o banner; enviando boas-vindas em texto.")
        fallback="🐾 <b>PIT PRÊMIOS</b>\\n\\n"+caption
        return send(chat,fallback,keyboard)

def admin(uid): return uid in ADMIN_IDS
def btn(label,data): return {"text":label,"callback_data":data}
def menu():
    return [[btn("👤 Meu perfil","profile"),btn("💰 Carteira","wallet")],
            [btn("🎯 Missões","missions"),btn("🎁 Check-in","daily")],
            [btn("🚀 Convidar","invite"),btn("🏆 Ranking","ranking")],
            [btn("💎 Clube VIP","vip"),btn("🎟️ Resgatar","redeem_info")],
            [btn("📜 Extrato","history"),btn("❓ Ajuda","help")]]
def back(): return [[btn("⬅️ Menu principal","home")]]

def start(m):
    u=m.get("from",{}); chat=m["chat"]["id"]; p=(m.get("text") or "").split(maxsplit=1)
    ref=int(p[1]) if len(p)>1 and p[1].isdigit() else None
    created,refid=db.register_user(u["id"],u.get("username"),u.get("first_name") or "",ref,POINTS_PER_REFERRAL)
    if created and refid and POINTS_PER_REFERRAL:
        try: send(refid,f"🎉 Você ganhou {POINTS_PER_REFERRAL} pontos por uma indicação!")
        except Exception: log.exception("Falha ao notificar indicador")
    global BOT_USERNAME
    pr=db.get_profile(u["id"])
    first=escape((u.get("first_name") or "participante")[:40])
    send_photo(chat,BANNER_URL,f"🐾 <b>Olá, {first}!</b> Bem-vindo ao PIT PRÊMIOS.\n\n💰 Carteira: <b>{pr['points']:,} pontos</b>\n👥 Convites: <b>{pr['referrals']}</b>\n🔥 Sequência: <b>{pr['daily_streak']} dias</b>\n\n<i>Seus pontos. Suas conquistas. Seus prêmios.</i>",menu())

def balance(chat,uid):
    u=db.get_user(uid); send(chat,f"💰 Saldo: <b>{u['points'] if u else 0} pontos</b>")

def ranking(chat):
    lines=["🏆 <b>TOP 10 PIT PRÊMIOS</b>"]
    for i,u in enumerate(db.ranking(),1):
        name=u["first_name"] or ("@"+u["username"] if u["username"] else str(u["user_id"]))
        lines.append(f"{i}. {escape(name)} — {u['points']} pts")
    send(chat,"\n".join(lines))

def daily(chat,uid):
    ok,streak=db.daily_claim(uid,DAILY_REWARD)
    if ok:
        send(chat,f"🎉 <b>CHECK-IN CONFIRMADO!</b>\nVocê recebeu <b>+{DAILY_REWARD} pontos</b>.\n🔥 Sequência atual: <b>{streak} dias</b>\n\n<i>Volte amanhã para manter sua sequência!</i>",back())
    else:
        send(chat,f"⏳ <b>Check-in já realizado!</b>\nSua sequência atual é de <b>{streak} dias</b>. Volte amanhã.",back())

def profile(chat,uid):
    p=db.get_profile(uid); u=db.get_user(uid)
    name=escape((u["first_name"] or "Participante")[:40]); vip="ATIVO 💎" if u and u["is_vip"] else "COMUM"
    send(chat,f"👤 <b>SEU PERFIL PIT</b>\n━━━━━━━━━━━━━━━━━━\nOlá, <b>{name}</b>\n🆔 ID: <code>{uid}</code>\n💰 Saldo: <b>{p['points']:,} pontos</b>\n👥 Amigos convidados: <b>{p['referrals']}</b>\n🔥 Sequência diária: <b>{p['daily_streak']} dias</b>\n💎 Categoria: <b>{vip}</b>\n📅 Membro desde: <code>{p['created_at'][:10]}</code>",back())
def invite(chat,uid):
    p=db.get_profile(uid); link=f"https://t.me/{BOT_USERNAME}?start={uid}"
    send(chat,f"🚀 <b>SEU LINK EXCLUSIVO</b>\n━━━━━━━━━━━━━━━━━━\nConvide amigos. Quando uma pessoa nova iniciar o bot pelo seu link, a indicação será registrada.\n\n🔗 <code>{link}</code>\n👥 Indicações confirmadas: <b>{p['referrals']}</b>\n🎁 Recompensa por indicação: <b>{POINTS_PER_REFERRAL} pontos</b>",[[btn("🏆 Top indicadores","toprefs")],btn("⬅️ Menu principal","home")])
def toprefs(chat):
    rows=db.top_referrals(); lines=["🚀 <b>CAMPEÕES DE INDICAÇÃO</b>","━━━━━━━━━━━━━━━━━━"]
    for i,r in enumerate(rows,1): lines.append(f"{i}. <b>{escape((r['first_name'] or str(r['user_id']))[:24])}</b> — {r['referrals']} amigos")
    if not rows: lines.append("As primeiras indicações ainda estão por vir.")
    send(chat,"\n".join(lines),back())
def missions(chat,uid):
    p=db.get_profile(uid); state="Disponível" if p["last_daily"]!=db.today() else "Concluída hoje"
    send(chat,f"🎯 <b>MISSÕES DO PIT</b>\n━━━━━━━━━━━━━━━━━━\n✅ Criar sua conta — <i>Concluída</i>\n🎁 Coletar bônus diário — <i>{state}</i>\n🚀 Convidar amigos — <i>{p['referrals']} confirmado(s)</i>\n📜 Consultar extrato — <i>Disponível</i>\n\n<i>Novas campanhas serão anunciadas nesta área.</i>",[[btn("🎁 Fazer check-in","daily"),btn("🚀 Convidar","invite")],btn("⬅️ Menu principal","home")])
def history(chat,uid):
    rows=db.history(uid,8); lines=["📜 <b>SEU EXTRATO</b>","━━━━━━━━━━━━━━━━━━"]
    if not rows: lines.append("Nenhuma movimentação registrada.")
    for r in rows:
        sign="+" if r["amount"]>0 else ""; icon="🟢" if r["amount"]>0 else "🔴"
        lines.append(f"{icon} <b>{sign}{r['amount']} pts</b> — {escape(r['reason'][:50])}\n<i>{r['created_at']}</i>")
    send(chat,"\n".join(lines),back())
def redeem_help(chat):
    send(chat,"🎟️ <b>CENTRAL DE RESGATES</b>\n━━━━━━━━━━━━━━━━━━\nMínimo: <b>"+str(MIN_REDEEM_POINTS)+" pontos</b>\nEnvie: <code>/resgatar PONTOS DESCRIÇÃO</code>\nExemplo: <code>/resgatar 100 Pix de R$ 5</code>",back())

def help_page(chat):
    send(chat,f"❓ <b>CENTRAL DE AJUDA</b>\n━━━━━━━━━━━━━━━━━━\n💰 Pontos: acumule participando das ações.\n🎁 Check-in: bônus uma vez por dia.\n🚀 Indicações: compartilhe seu link pessoal.\n🏆 Ranking: veja os participantes com mais pontos.\n🎟️ Resgates: /resgatar PONTOS DESCRIÇÃO. Mínimo {MIN_REDEEM_POINTS} pontos.\n💎 VIP: ativação pela administração.",back())

def command(m):
    t=m.get("text") or ""; p=t.split(maxsplit=2); cmd=p[0].split("@")[0].lower()
    chat=m["chat"]["id"]; uid=m.get("from",{}).get("id")
    if cmd=="/start": start(m)
    elif cmd=="/saldo": balance(chat,uid)
    elif cmd=="/ranking": ranking(chat)
    elif cmd=="/diario": daily(chat,uid)
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
    elif cmd in ("/admin","/stats","/addpoints","/setvip","/pedidos","/broadcast","/usuario") and admin(uid):
        if cmd=="/admin": send(chat,"🛠️ <b>PAINEL ADMINISTRATIVO</b>\n/stats\n/usuario ID\n/addpoints ID QUANTIDADE\n/setvip ID on|off\n/pedidos\n/broadcast MENSAGEM")
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
        elif cmd=="/pedidos":
            rows=db.pending_redemptions()
            if not rows: send(chat,"Nenhum pedido pendente."); return
            for r in rows:
                kb=[[{"text":"Aprovar","callback_data":f"review:{r['id']}:yes"},{"text":"Rejeitar","callback_data":f"review:{r['id']}:no"}]]
                send(chat,f"Pedido #{r['id']}\nUsuário: {r['user_id']}\nPontos: {r['points']}\nPrêmio: {escape(r['reward'])}",kb)
    elif cmd in ("/admin","/stats","/addpoints","/setvip","/pedidos","/broadcast","/usuario"): pass
    else: send(chat,"Não entendi. Use /start para abrir o menu.")

def callback(c):
    data=c.get("data",""); uid=c.get("from",{}).get("id"); msg=c.get("message",{}); chat=msg.get("chat",{}).get("id")
    api("answerCallbackQuery",{"callback_query_id":c["id"]})
    if chat is None: return
    if data=="home": api("editMessageText",{"chat_id":chat,"message_id":msg["message_id"],"text":"🐾 <b>PIT PRÊMIOS</b>\nSua central de pontos, conquistas e recompensas.","parse_mode":"HTML","reply_markup":{"inline_keyboard":menu()}})
    elif data=="profile": profile(chat,uid)
    elif data=="wallet": balance(chat,uid)
    elif data=="invite": invite(chat,uid)
    elif data=="toprefs": toprefs(chat)
    elif data=="missions": missions(chat,uid)
    elif data=="history": history(chat,uid)
    elif data=="help": help_page(chat)
    elif data=="redeem_info": redeem_help(chat)
    elif data=="balance": balance(chat,uid)
    elif data=="ranking": ranking(chat)
    elif data=="daily": daily(chat,uid)
    elif data=="vip":
        u=db.get_user(uid); send(chat,"💎 VIP: "+("ATIVO" if u and u["is_vip"] else "INATIVO")+". Consulte a administração.")
    elif data=="help_redeem": send(chat,f"Para solicitar: /resgatar PONTOS DESCRIÇÃO\nMínimo: {MIN_REDEEM_POINTS} pontos.")
    elif data.startswith("review:"):
        if not admin(uid): return
        _,rid,decision=data.split(":"); result=db.review_redemption(int(rid),uid,decision=="yes")
        if not result: return
        status="aprovado" if decision=="yes" else "rejeitado; pontos devolvidos"
        api("editMessageText",{"chat_id":chat,"message_id":msg["message_id"],"text":msg.get("text","")+f"\nStatus: {status}","parse_mode":"HTML"})
        try: send(result["user_id"],f"Seu resgate #{rid} foi {status}.")
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
                        elif m.get("chat",{}).get("type")=="private": send(m["chat"]["id"],"Não entendi. Use /start para abrir o menu.")
                    elif "callback_query" in update: callback(update["callback_query"])
                except Exception: log.exception("Erro ao processar atualização %s",update.get("update_id"))
        except KeyboardInterrupt: break
        except Exception: log.exception("Falha na conexão; nova tentativa em 5 segundos"); time.sleep(5)

if __name__=="__main__": main()
