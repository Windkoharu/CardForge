--[==[ 霆铸炉·磁轨护壁
     CardForge 2.0 生成 · 卡种=陷阱（frame=trap） · tier=1
     由效果 IR 投影而来；效果种类缺失的部分以 -- [CardForge] 注释标出。
     ⚑ negate 的条件函数只判断「发动的不是自己」（怪兽效果类时点会额外认 re:IsMonsterEffect()）；属性/字段/卡种那类限定请人工补写
]==]
local s,id=GetID()
function s.initial_effect(c)
	--1. 那个发动无效并破坏
	local e1=Effect.CreateEffect(c)
	e1:SetDescription(aux.Stringid(id,0))
	e1:SetCategory(CATEGORY_NEGATE+CATEGORY_DESTROY)
	e1:SetType(EFFECT_TYPE_QUICK_F)
	e1:SetProperty(EFFECT_FLAG_DELAY+EFFECT_FLAG_DAMAGE_STEP+EFFECT_FLAG_DAMAGE_CAL)
	e1:SetCode(EVENT_CHAINING)
	e1:SetCountLimit(1,id)
	e1:SetCost(s.cost1)
	e1:SetCondition(s.con1)
	e1:SetOperation(s.op1)
	c:RegisterEffect(e1)
end
s.listed_series={0x1003}

function s.con1(e,tp,eg,ep,ev,re,r,rp)
	return ep~=tp and re:IsMonsterEffect()
end

function s.op1(e,tp,eg,ep,ev,re,r,rp)
	if Duel.NegateActivation(ev) and re:GetHandler():IsRelateToEffect(re) then
		Duel.Destroy(eg,REASON_EFFECT)
	end
end

function s.cfil1(c)
	return c:IsSetCard(0x1003) and c:IsAbleToGraveAsCost()
end

function s.cost1(e,tp,eg,ep,ev,re,r,rp,chk)
	if chk==0 then return Duel.IsExistingMatchingCard(s.cfil1,tp,LOCATION_ONFIELD,0,1,nil) end
	Duel.Hint(HINT_SELECTMSG,tp,HINTMSG_TOGRAVE)
	local g=Duel.SelectMatchingCard(tp,s.cfil1,tp,LOCATION_ONFIELD,0,1,1,nil)
	Duel.SendtoGrave(g,REASON_COST)
end
