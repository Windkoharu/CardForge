--[==[ 圣痕的龙骑士 露米艾尔
     CardForge 2.0 生成 · 卡种=融合（frame=fusion） · tier=1
     由效果 IR 投影而来；效果种类缺失的部分以 -- [CardForge] 注释标出。
     ⚑ negate_card 的作用区域按对象取 LOCATION_ONFIELD；若只想无效怪兽效果请改挂 EFFECT_DISABLE+MONSTER 限定
     ⚑ negate 的条件函数只判断「发动的不是自己」（怪兽效果类时点会额外认 re:IsMonsterEffect()）；属性/字段/卡种那类限定请人工补写
]==]
local s,id=GetID()
function s.initial_effect(c)
	--融合素材条件
	Fusion.AddProcMix(c,true,true,s.mat0_0,s.mat0_0,s.mat0_0)
	c:EnableReviveLimit()
	--额外召唤方法：把上记的卡除外的接触召唤（仍按融合召唤类型结算）
	Fusion.AddContactProc(c,s.cgrp0_0,s.ctop0_0,nil,nil,SUMMON_TYPE_FUSION)
	--不能作为融合素材
	local e_lock_fusion=Effect.CreateEffect(c)
	e_lock_fusion:SetType(EFFECT_TYPE_SINGLE)
	e_lock_fusion:SetProperty(EFFECT_FLAG_CANNOT_DISABLE+EFFECT_FLAG_UNCOPYABLE)
	e_lock_fusion:SetCode(EFFECT_CANNOT_BE_FUSION_MATERIAL)
	e_lock_fusion:SetValue(1)
	c:RegisterEffect(e_lock_fusion)
	--召唤条件：只能用本卡种的召唤方式特殊召唤
	local e_sp=Effect.CreateEffect(c)
	e_sp:SetType(EFFECT_TYPE_SINGLE)
	e_sp:SetProperty(EFFECT_FLAG_CANNOT_DISABLE+EFFECT_FLAG_UNCOPYABLE)
	e_sp:SetCode(EFFECT_SPSUMMON_CONDITION)
	e_sp:SetValue(aux.fuslimit)
	c:RegisterEffect(e_sp)
	--2. ①：1回合1次，以对方场上1张表侧表示的卡为对象才能发动。那张卡的效果直到回合结
	local e2=Effect.CreateEffect(c)
	e2:SetDescription(aux.Stringid(id,0))
	e2:SetCategory(CATEGORY_NEGATE)
	e2:SetType(EFFECT_TYPE_QUICK_O)
	e2:SetProperty(EFFECT_FLAG_CARD_TARGET)
	e2:SetRange(LOCATION_MZONE)
	e2:SetCode(EVENT_FREE_CHAIN)
	e2:SetCountLimit(1,id)
	e2:SetTarget(s.tg2)
	e2:SetOperation(s.op2)
	c:RegisterEffect(e2)
	--3. ②：1回合1次，对方把怪兽的效果发动时，从卡组把1只战士族怪兽送去墓地才能发动。
	local e3=Effect.CreateEffect(c)
	e3:SetDescription(aux.Stringid(id,1))
	e3:SetCategory(CATEGORY_NEGATE+CATEGORY_DESTROY)
	e3:SetType(EFFECT_TYPE_FIELD+EFFECT_TYPE_TRIGGER_O)
	e3:SetProperty(EFFECT_FLAG_DELAY)
	e3:SetRange(LOCATION_MZONE)
	e3:SetCode(EVENT_CHAINING)
	e3:SetCountLimit(1,{id,1})
	e3:SetCost(s.cost3)
	e3:SetCondition(s.con3)
	e3:SetOperation(s.op3)
	c:RegisterEffect(e3)
	--4. ③：这张卡被战斗·效果破坏的场合才能发动。从自己墓地选1只战士族怪兽特殊召唤。
	local e4=Effect.CreateEffect(c)
	e4:SetDescription(aux.Stringid(id,2))
	e4:SetCategory(CATEGORY_SPECIAL_SUMMON)
	e4:SetType(EFFECT_TYPE_SINGLE+EFFECT_TYPE_TRIGGER_O)
	e4:SetProperty(EFFECT_FLAG_DELAY)
	e4:SetRange(LOCATION_MZONE)
	e4:SetCode(EVENT_DESTROYED)
	e4:SetCondition(s.con4)
	e4:SetTarget(s.tg4)
	e4:SetOperation(s.op4)
	c:RegisterEffect(e4)
end
s.listed_series={0x1000}

function s.mat0_0(c)
	return c:IsSetCard(0x1000) and c:IsRace(RACE_WARRIOR)
end

function s.cfil0_0(c)
	return (c:IsSetCard(0x1000) and c:IsRace(RACE_WARRIOR)) and c:IsAbleToRemoveAsCost()
end

function s.cgrp0_0(tp)
	return Duel.GetMatchingGroup(s.cfil0_0,tp,LOCATION_MZONE,LOCATION_MZONE,nil)
end

function s.ctop0_0(g,tp,c)
	Duel.Remove(g,POS_FACEUP,REASON_COST|REASON_MATERIAL)
end

function s.fil2(c)
	return c:IsFaceup()
end

function s.tg2(e,tp,eg,ep,ev,re,r,rp,chk,chkc)
	if chkc then return chkc:IsOnField() and chkc:IsFaceup() end
	if chk==0 then return Duel.IsExistingTarget(s.fil2,tp,0,LOCATION_ONFIELD,1,nil) end
	Duel.Hint(HINT_SELECTMSG,tp,HINTMSG_FACEUP)
	local g=Duel.SelectTarget(tp,s.fil2,tp,0,LOCATION_ONFIELD,1,1,nil)
	Duel.SetOperationInfo(0,CATEGORY_NEGATE,g,1,0,0)
end

function s.op2(e,tp,eg,ep,ev,re,r,rp)
	local tc=Duel.GetFirstTarget()
	if tc and tc:IsFaceup() and tc:IsRelateToEffect(e) then
		local e1=Effect.CreateEffect(e:GetHandler())
			e1:SetType(EFFECT_TYPE_SINGLE)
			e1:SetCode(EFFECT_DISABLE)
			e1:SetReset(RESET_EVENT+RESETS_STANDARD+RESET_PHASE+PHASE_END)
			tc:RegisterEffect(e1)
		local e2=Effect.CreateEffect(e:GetHandler())
			e2:SetType(EFFECT_TYPE_SINGLE)
			e2:SetCode(EFFECT_DISABLE_EFFECT)
			e2:SetReset(RESET_EVENT+RESETS_STANDARD+RESET_PHASE+PHASE_END)
			tc:RegisterEffect(e2)
	end
end

function s.con3(e,tp,eg,ep,ev,re,r,rp)
	return ep~=tp and re:IsMonsterEffect()
end

function s.op3(e,tp,eg,ep,ev,re,r,rp)
	if Duel.NegateActivation(ev) and re:GetHandler():IsRelateToEffect(re) then
		Duel.Destroy(eg,REASON_EFFECT)
	end
end

function s.cfil3(c)
	return c:IsRace(RACE_WARRIOR) and c:IsAbleToGraveAsCost()
end

function s.cost3(e,tp,eg,ep,ev,re,r,rp,chk)
	if chk==0 then return Duel.IsExistingMatchingCard(s.cfil3,tp,LOCATION_DECK,0,1,nil) end
	Duel.Hint(HINT_SELECTMSG,tp,HINTMSG_TOGRAVE)
	local g=Duel.SelectMatchingCard(tp,s.cfil3,tp,LOCATION_DECK,0,1,1,nil)
	Duel.SendtoGrave(g,REASON_COST)
end

function s.fil4(c,e,tp)
	return c:IsRace(RACE_WARRIOR) and c:IsType(TYPE_MONSTER) and c:IsCanBeSpecialSummoned(e,0,tp,false,false)
end

function s.tg4(e,tp,eg,ep,ev,re,r,rp,chk)
	if chk==0 then return Duel.GetLocationCount(tp,LOCATION_MZONE)>0 and Duel.IsExistingMatchingCard(s.fil4,tp,LOCATION_GRAVE,0,1,e:GetHandler(),e,tp) end
	Duel.SetOperationInfo(0,CATEGORY_SPECIAL_SUMMON,nil,1,tp,LOCATION_GRAVE)
end

function s.op4(e,tp,eg,ep,ev,re,r,rp)
	if Duel.GetLocationCount(tp,LOCATION_MZONE)<=0 then return end
	Duel.Hint(HINT_SELECTMSG,tp,HINTMSG_SPSUMMON)
	local g=Duel.SelectMatchingCard(tp,s.fil4,tp,LOCATION_GRAVE,0,1,1,e:GetHandler(),e,tp)
	if #g>0 then
		Duel.SpecialSummon(g,0,tp,tp,false,false,POS_FACEUP)
	end
end

function s.con4(e,tp,eg,ep,ev,re,r,rp)
	local c=e:GetHandler()
	return c:IsReason(REASON_DESTROY) and c:IsPreviousLocation(LOCATION_ONFIELD)
end
