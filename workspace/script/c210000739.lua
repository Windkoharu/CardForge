--[==[ xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
     CardForge 2.0 生成 · 卡种=融合灵摆（frame=fusion_pendulum） · tier=1
     由效果 IR 投影而来；效果种类缺失的部分以 -- [CardForge] 注释标出。
     ⚑ 融合素材为空，未生成 Fusion.AddProcMix
     ⚑ 效果 kind=０ 已降级：kind 不在效果注册表里
     ⚑ 效果 kind= 已降级：kind 不在效果注册表里
     ⚑ 效果 kind=不存在的种类 已降级：kind 不在效果注册表里
     ⚑ stat_change 没有时限信息，默认给「离场 + 回合结束」双重失效（卡文若写「直到回合结束为止」请设 params['until_end_turn']=True）
     ⚑ 效果 kind=__init__ 已降级：kind 不在效果注册表里
     ⚑ 效果 kind=frag_destroy 已降级：kind 不在效果注册表里
]==]
local s,id=GetID()
function s.initial_effect(c)
	--灵摆召唤流程（左右刻度编码在 cdb 的 level 字段里，脚本不用写）
	Pendulum.AddProcedure(c)
	--融合素材条件
	-- [CardForge] 融合素材条件为空：请在「召唤条件」里填写素材，未生成 Fusion.AddProcMix
	-- [CardForge] 效果 kind=０ 暂无脚本片段，需人工补写：kind 不在效果注册表里
	-- 原卡文：xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
	-- [CardForge] 效果 kind= 暂无脚本片段，需人工补写：kind 不在效果注册表里

	-- [CardForge] 效果 kind=不存在的种类 暂无脚本片段，需人工补写：kind 不在效果注册表里
	-- 原卡文：①：乱码 ñ中文
	--2. ①把②③
	local e2=Effect.CreateEffect(c)
	e2:SetDescription(aux.Stringid(id,0))
	e2:SetCategory(CATEGORY_TOHAND+CATEGORY_SEARCH)
	e2:SetType(EFFECT_TYPE_SINGLE)
	e2:SetRange(LOCATION_MZONE)
	e2:SetCountLimit(1,id)
	e2:SetCost(s.cost2)
	e2:SetTarget(s.tg2)
	e2:SetOperation(s.op2)
	c:RegisterEffect(e2)
	--3. xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
	local e3=Effect.CreateEffect(c)
	e3:SetDescription(aux.Stringid(id,1))
	e3:SetCategory(CATEGORY_ATKCHANGE)
	e3:SetType(EFFECT_TYPE_SINGLE)
	e3:SetProperty(EFFECT_FLAG_CARD_TARGET)
	e3:SetRange(LOCATION_MZONE)
	e3:SetCountLimit(1,{id,1},EFFECT_COUNT_CODE_DUEL)
	e3:SetTarget(s.tg3)
	e3:SetOperation(s.op3)
	c:RegisterEffect(e3)
	-- [CardForge] 效果 kind=__init__ 暂无脚本片段，需人工补写：kind 不在效果注册表里

	-- [CardForge] 效果 kind=frag_destroy 暂无脚本片段，需人工补写：kind 不在效果注册表里
	-- 原卡文：①：乱码 ñ中文
end
s.listed_series={0x9, 0x63}

function s.fil2(c)
	return c:IsAbleToHand()
end

function s.tg2(e,tp,eg,ep,ev,re,r,rp,chk)
	if chk==0 then return Duel.IsExistingMatchingCard(s.fil2,tp,LOCATION_MZONE,0,99,nil) end
	Duel.SetOperationInfo(0,CATEGORY_TOHAND,nil,99,tp,LOCATION_MZONE)
end

function s.op2(e,tp,eg,ep,ev,re,r,rp)
	Duel.Hint(HINT_SELECTMSG,tp,HINTMSG_ATOHAND)
	local g=Duel.SelectMatchingCard(tp,s.fil2,tp,LOCATION_MZONE,0,99,99,nil)
	if #g>0 then
		Duel.SendtoHand(g,nil,REASON_EFFECT)
		Duel.ConfirmCards(1-tp,g)
	end
end

function s.cost2(e,tp,eg,ep,ev,re,r,rp,chk)
	if chk==0 then return Duel.CheckLPCost(tp,99) end
	Duel.PayLPCost(tp,99)
end

function s.fil3(c)
	return c:IsSetCard(0x9) and c:IsType(TYPE_MONSTER) and c:IsFaceup()
end

function s.tg3(e,tp,eg,ep,ev,re,r,rp,chk,chkc)
	if chkc then return chkc:IsLocation(LOCATION_MZONE) and chkc:IsFaceup() end
	if chk==0 then return Duel.IsExistingTarget(s.fil3,tp,LOCATION_MZONE,LOCATION_MZONE,1,nil) end
	Duel.Hint(HINT_SELECTMSG,tp,HINTMSG_TARGET)
	local g=Duel.SelectTarget(tp,s.fil3,tp,LOCATION_MZONE,LOCATION_MZONE,99,99,nil)
	Duel.SetOperationInfo(0,CATEGORY_ATKCHANGE,g,#g,0,0)
end

function s.op3(e,tp,eg,ep,ev,re,r,rp)
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
