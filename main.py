import asyncio, logging
from aiogram import Bot,Dispatcher,F
from aiogram.filters import Command,CommandStart
from aiogram.types import Message,CallbackQuery,InlineKeyboardMarkup,InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from config import BOT_TOKEN,ADMIN_IDS,POINTS_PER_REFERRAL,DAILY_REWARD,MIN_REDEEM_POINTS
import database as db

logging.basicConfig(level=logging.INFO)
bot=Bot(BOT_TOKEN,default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp=Dispatcher()
def admin(uid): return uid in ADMIN_IDS
def menu():
    return InlineKeyboardMarkup(inline_keyboard=[
      [InlineKeyboardButton(text="💰 Meu saldo",callback_data="balance"),InlineKeyboardButton(text="🏆 Ranking",callback_data="ranking")],
      [InlineKeyboardButton(text="🎁 Bônus diário",callback_data="daily"),InlineKeyboardButton(text="💎 VIP",callback_data="vip")],
      [InlineKeyboardButton(text="📤 Como resgatar",callback_data="help_redeem")]])

@dp.message(CommandStart())
async def start(m:Message):
    parts=(m.text or "").split(maxsplit=1)
    ref=int(parts[1]) if len(parts)>1 and parts[1].isdigit() else None
    created,ref_id=await db.register_user(m.from_user.id,m.from_user.username,m.from_user.first_name or "",ref)
    if created and ref_id and POINTS_PER_REFERRAL:
        await db.add_points(ref_id,POINTS_PER_REFERRAL,f"Indicação de {m.from_user.id}")
        try: await bot.send_message(ref_id,f"🎉 Você ganhou {POINTS_PER_REFERRAL} pontos por uma indicação!")
        except Exception: logging.exception("Falha ao notificar indicador")
    me=await bot.get_me()
    link=f"https://t.me/{me.username}?start={m.from_user.id}"
    await m.answer(f"🐾 <b>Bem-vindo ao PIT PRÊMIOS!</b>\nAcumule pontos e troque por recompensas.\n\nSeu link: <code>{link}</code>",reply_markup=menu())

@dp.message(Command("saldo"))
@dp.callback_query(F.data=="balance")
async def balance(e):
    uid=e.from_user.id; u=await db.get_user(uid); value=u["points"] if u else 0
    if isinstance(e,Message): await e.answer(f"💰 Saldo: <b>{value} pontos</b>")
    else: await e.answer(); await e.message.answer(f"💰 Saldo: <b>{value} pontos</b>")

@dp.message(Command("ranking"))
@dp.callback_query(F.data=="ranking")
async def ranking(e):
    rows=await db.ranking()
    lines=["🏆 <b>TOP 10 PIT PRÊMIOS</b>"]
    for i,u in enumerate(rows,1):
        name=u["first_name"] or (("@"+u["username"]) if u["username"] else str(u["user_id"]))
        lines.append(f"{i}. {name} — {u['points']} pts")
    if isinstance(e,Message): await e.answer("\n".join(lines))
    else: await e.answer(); await e.message.answer("\n".join(lines))

@dp.message(Command("diario"))
@dp.callback_query(F.data=="daily")
async def daily(e):
    ok=await db.daily_claim(e.from_user.id,DAILY_REWARD)
    msg=f"🎉 Você recebeu {DAILY_REWARD} pontos!" if ok else "⏳ Você já coletou o bônus de hoje."
    if isinstance(e,Message): await e.answer(msg)
    else: await e.answer(); await e.message.answer(msg)

@dp.callback_query(F.data=="vip")
async def vip(c:CallbackQuery):
    u=await db.get_user(c.from_user.id)
    await c.answer()
    await c.message.answer("💎 VIP: "+("ATIVO" if u and u["is_vip"] else "INATIVO")+". Consulte a administração.")

@dp.callback_query(F.data=="help_redeem")
async def redeem_help(c:CallbackQuery):
    await c.answer()
    await c.message.answer(f"Para solicitar: /resgatar PONTOS DESCRIÇÃO\nMínimo: {MIN_REDEEM_POINTS} pontos.")

@dp.message(Command("resgatar"))
async def redeem(m:Message):
    p=(m.text or "").split(maxsplit=2)
    if len(p)<3 or not p[1].isdigit():
        await m.answer("Use /resgatar PONTOS DESCRIÇÃO"); return
    points=int(p[1]); reward=p[2].strip()
    if points<MIN_REDEEM_POINTS or points>10000000 or not reward:
        await m.answer(f"Resgate mínimo: {MIN_REDEEM_POINTS} pontos."); return
    try: rid=await db.create_redemption(m.from_user.id,points,reward)
    except ValueError as ex: await m.answer(str(ex)); return
    await m.answer(f"✅ Pedido #{rid} enviado. Os pontos ficam reservados até análise.")
    for aid in ADMIN_IDS:
        try: await bot.send_message(aid,f"Novo resgate #{rid}\nUsuário: {m.from_user.id}\nPontos: {points}\nPrêmio: {reward}")
        except Exception: logging.exception("Falha ao notificar admin")

@dp.message(Command("admin"))
async def admin_panel(m:Message):
    if not admin(m.from_user.id): return
    await m.answer("/stats\n/addpoints ID QUANTIDADE\n/setvip ID on|off\n/pedidos\n/aprovar ID\n/rejeitar ID")

@dp.message(Command("stats"))
async def stats(m:Message):
    if not admin(m.from_user.id): return
    s=await db.stats()
    await m.answer(f"📊 Usuários: {s['users']}\nPontos: {s['points']}\nResgates pendentes: {s['pending']}")

@dp.message(Command("addpoints"))
async def addpoints(m:Message):
    if not admin(m.from_user.id): return
    p=(m.text or "").split()
    if len(p)!=3 or not p[1].isdigit() or not p[2].lstrip("-").isdigit():
        await m.answer("Use /addpoints ID QUANTIDADE"); return
    amount=int(p[2])
    if not amount or abs(amount)>1000000: await m.answer("Quantidade inválida."); return
    try: await db.add_points(int(p[1]),amount,f"Ajuste por admin {m.from_user.id}")
    except ValueError as ex: await m.answer(str(ex)); return
    await m.answer("✅ Saldo atualizado.")

@dp.message(Command("setvip"))
async def setvip(m:Message):
    if not admin(m.from_user.id): return
    p=(m.text or "").split()
    if len(p)!=3 or not p[1].isdigit() or p[2].lower() not in ("on","off"):
        await m.answer("Use /setvip ID on|off"); return
    await db.set_vip(int(p[1]),p[2].lower()=="on")
    await m.answer("✅ VIP atualizado.")

@dp.message(Command("pedidos"))
async def pedidos(m:Message):
    if not admin(m.from_user.id): return
    rows=await db.pending_redemptions()
    if not rows: await m.answer("Nenhum pedido pendente."); return
    for r in rows:
        kb=InlineKeyboardMarkup(inline_keyboard=[[
          InlineKeyboardButton(text="Aprovar",callback_data=f"review:{r['id']}:yes"),
          InlineKeyboardButton(text="Rejeitar",callback_data=f"review:{r['id']}:no")]])
        await m.answer(f"Pedido #{r['id']}\nUsuário: {r['user_id']}\nPontos: {r['points']}\nPrêmio: {r['reward']}",reply_markup=kb)

@dp.callback_query(F.data.startswith("review:"))
async def review(c:CallbackQuery):
    if not admin(c.from_user.id): await c.answer("Acesso negado.",show_alert=True); return
    _,raw,decision=c.data.split(":")
    result=await db.review_redemption(int(raw),c.from_user.id,decision=="yes")
    if not result: await c.answer("Pedido já analisado.",show_alert=True); return
    status="aprovado" if decision=="yes" else "rejeitado; pontos devolvidos"
    await c.answer("Análise concluída.")
    await c.message.edit_text(c.message.text+f"\nStatus: {status}")
    try: await bot.send_message(result["user_id"],f"Seu resgate #{raw} foi {status}.")
    except Exception: logging.exception("Falha ao avisar usuário")

@dp.message()
async def fallback(m:Message):
    await m.answer("Não entendi. Use /start para abrir o menu.")

async def main():
    await db.init_db()
    logging.info("PIT PRÊMIOS iniciado")
    await dp.start_polling(bot,allowed_updates=dp.resolve_used_update_types())
if __name__=="__main__": asyncio.run(main())
