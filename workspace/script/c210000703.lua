--[==[ xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
     CardForge 2.0 生成 · 卡种=陷阱（frame=trap） · tier=1
     由效果 IR 投影而来；效果种类缺失的部分以 -- [CardForge] 注释标出。
     ⚑ stat_change 没有时限信息，默认给「离场 + 回合结束」双重失效（卡文若写「直到回合结束为止」请设 params['until_end_turn']=True）
     ⚑ 效果 kind=__init__ 已降级：kind 不在效果注册表里
     ⚑ 效果 kind=frag_destroy 已降级：kind 不在效果注册表里
     ⚑ 效果 kind=SSUMMON 已降级：kind 不在效果注册表里
     ⚑ 效果 kind=０ 已降级：kind 不在效果注册表里
     ⚑ 效果 kind= 已降级：kind 不在效果注册表里
     ⚑ 效果 kind=不存在的种类 已降级：kind 不在效果注册表里
]==]
local s,id=GetID()
function s.initial_effect(c)
	--1. xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
	local e1=Effect.CreateEffect(c)
	e1:SetDescription(aux.Stringid(id,0))
	e1:SetCategory(CATEGORY_ATKCHANGE)
	e1:SetType(EFFECT_TYPE_ACTIVATE)
	e1:SetProperty(EFFECT_FLAG_CARD_TARGET)
	e1:SetCode(EVENT_FREE_CHAIN)
	e1:SetTarget(s.tg1)
	e1:SetOperation(s.op1)
	c:RegisterEffect(e1)
	-- [CardForge] 效果 kind=__init__ 暂无脚本片段，需人工补写：kind 不在效果注册表里

	-- [CardForge] 效果 kind=frag_destroy 暂无脚本片段，需人工补写：kind 不在效果注册表里
	-- 原卡文：①：乱码 ñ中文
	-- [CardForge] 效果 kind=SSUMMON 暂无脚本片段，需人工补写：kind 不在效果注册表里
	-- 原卡文：①把②③
	-- [CardForge] 效果 kind=０ 暂无脚本片段，需人工补写：kind 不在效果注册表里
	-- 原卡文：xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
	-- [CardForge] 效果 kind= 暂无脚本片段，需人工补写：kind 不在效果注册表里

	-- [CardForge] 效果 kind=不存在的种类 暂无脚本片段，需人工补写：kind 不在效果注册表里
	-- 原卡文：①：乱码 ñ中文
end
s.listed_series={0x1001, 0x2}

function s.fil1(c)
	return c:IsType(TYPE_MONSTER) and c:IsFaceup()
end

function s.tg1(e,tp,eg,ep,ev,re,r,rp,chk,chkc)
	if chkc then return chkc:IsLocation(LOCATION_MZONE) and chkc:IsFaceup() end
	if chk==0 then return Duel.IsExistingTarget(s.fil1,tp,LOCATION_MZONE,LOCATION_MZONE,1,nil) end
	Duel.Hint(HINT_SELECTMSG,tp,HINTMSG_TARGET)
	local g=Duel.SelectTarget(tp,s.fil1,tp,LOCATION_MZONE,LOCATION_MZONE,99,99,nil)
	Duel.SetOperationInfo(0,CATEGORY_ATKCHANGE,g,#g,0,0)
end

function s.op1(e,tp,eg,ep,ev,re,r,rp)
	local tc=Duel.GetFirstTarget()
	if tc and tc:IsFaceup() and tc:IsRelateToEffect(e) then
		local e1=Effect.CreateEffect(e:GetHandler())
			e1:SetType(EFFECT_TYPE_SINGLE)
			e1:SetCode(EFFECT_UPDATE_ATTACK)
			e1:SetValue(99)
			e1:SetReset(RESET_EVENT+RESET_PHASE+PHASE_END)
			tc:RegisterEffect(e1)
	end
end
