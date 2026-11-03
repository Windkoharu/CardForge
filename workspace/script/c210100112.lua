--[==[ 霆铸天轨 宙斯
     CardForge 2.0 生成 · 卡种=超量（frame=xyz） · tier=1
     由效果 IR 投影而来；效果种类缺失的部分以 -- [CardForge] 注释标出。
]==]
local s,id=GetID()
function s.initial_effect(c)
	--超量素材条件
	Xyz.AddProcedure(c,s.mat0_0,4,2)
	c:EnableReviveLimit()
	--2. 把…除外
	local e2=Effect.CreateEffect(c)
	e2:SetDescription(aux.Stringid(id,0))
	e2:SetCategory(CATEGORY_REMOVE)
	e2:SetType(EFFECT_TYPE_QUICK_O)
	e2:SetProperty(EFFECT_FLAG_CARD_TARGET)
	e2:SetRange(LOCATION_MZONE)
	e2:SetCode(EVENT_FREE_CHAIN)
	e2:SetCountLimit(1,id)
	e2:SetCost(s.cost2)
	e2:SetTarget(s.tg2)
	e2:SetOperation(s.op2)
	c:RegisterEffect(e2)
end
s.listed_series={0x1003}

function s.mat0_0(c)
	return c:IsSetCard(0x1003) and c:IsLevel(4)
end

function s.fil2(c)
	return c:IsAbleToRemove()
end

function s.tg2(e,tp,eg,ep,ev,re,r,rp,chk,chkc)
	if chkc then return chkc:IsLocation(LOCATION_ONFIELD) and s.fil2(chkc) end
	if chk==0 then return Duel.IsExistingTarget(s.fil2,tp,0,LOCATION_ONFIELD,1,nil) end
	Duel.Hint(HINT_SELECTMSG,tp,HINTMSG_REMOVE)
	local g=Duel.SelectTarget(tp,s.fil2,tp,0,LOCATION_ONFIELD,1,1,nil)
	Duel.SetOperationInfo(0,CATEGORY_REMOVE,g,#g,0,0)
end

function s.op2(e,tp,eg,ep,ev,re,r,rp)
	local tc=Duel.GetFirstTarget()
	if tc and tc:IsRelateToEffect(e) then
		Duel.Remove(tc,POS_FACEUP,REASON_EFFECT)
	end
end

function s.cost2(e,tp,eg,ep,ev,re,r,rp,chk)
	local sc=e:GetHandler()
	if chk==0 then return sc:CheckRemoveOverlayCard(tp,1,REASON_COST) end
	sc:RemoveOverlayCard(tp,1,1,REASON_COST)
end
