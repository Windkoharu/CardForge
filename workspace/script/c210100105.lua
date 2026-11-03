--[==[ 霆铸的余热回收者
     CardForge 2.0 生成 · 卡种=效果（frame=effect） · tier=1
     由效果 IR 投影而来；效果种类缺失的部分以 -- [CardForge] 注释标出。
]==]
local s,id=GetID()
function s.initial_effect(c)
	--1. 从墓地把…加入手卡
	local e1=Effect.CreateEffect(c)
	e1:SetDescription(aux.Stringid(id,0))
	e1:SetCategory(CATEGORY_TOHAND+CATEGORY_SEARCH)
	e1:SetType(EFFECT_TYPE_SINGLE+EFFECT_TYPE_TRIGGER_O)
	e1:SetProperty(EFFECT_FLAG_DELAY)
	e1:SetRange(LOCATION_GRAVE)
	e1:SetCode(EVENT_TO_GRAVE)
	e1:SetCountLimit(1,{id,1})
	e1:SetCondition(s.con1)
	e1:SetTarget(s.tg1)
	e1:SetOperation(s.op1)
	c:RegisterEffect(e1)
end
s.listed_series={0x1003}

function s.fil1(c)
	return c:IsSetCard(0x1003) and c:IsType(TYPE_MONSTER) and c:IsAbleToHand()
end

function s.tg1(e,tp,eg,ep,ev,re,r,rp,chk)
	if chk==0 then return Duel.IsExistingMatchingCard(s.fil1,tp,LOCATION_GRAVE,0,1,e:GetHandler()) end
	Duel.SetOperationInfo(0,CATEGORY_TOHAND,nil,1,tp,LOCATION_GRAVE)
end

function s.op1(e,tp,eg,ep,ev,re,r,rp)
	Duel.Hint(HINT_SELECTMSG,tp,HINTMSG_ATOHAND)
	local g=Duel.SelectMatchingCard(tp,s.fil1,tp,LOCATION_GRAVE,0,1,1,e:GetHandler())
	if #g>0 then
		Duel.SendtoHand(g,nil,REASON_EFFECT)
		Duel.ConfirmCards(1-tp,g)
	end
end

function s.con1(e,tp,eg,ep,ev,re,r,rp)
	local c=e:GetHandler()
	return c:IsPreviousLocation(LOCATION_ONFIELD) and c:IsLocation(LOCATION_GRAVE)
end
