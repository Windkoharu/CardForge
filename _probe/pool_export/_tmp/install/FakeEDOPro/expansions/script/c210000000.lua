--[[ 焰刃的见习剑士 ]]
local s,id=GetID()
function s.initial_effect(c)
	local e1=Effect.CreateEffect(c)
	e1:SetDescription(aux.Stringid(id,0))
	c:RegisterEffect(e1)
end
