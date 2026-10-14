--[==[ c210000708
     CardForge 2.0 生成 · 卡种=技能卡（frame=skill） · tier=1
     由效果 IR 投影而来；效果种类缺失的部分以 -- [CardForge] 注释标出。
]==]
local s,id=GetID()
function s.initial_effect(c)
	--技能卡：主阶段・无连锁时才能发动（判定见 Auxiliary.CanActivateSkill）
	local e0=Effect.CreateEffect(c)
	e0:SetType(EFFECT_TYPE_ACTIVATE)
	e0:SetCode(EVENT_FREE_CHAIN)
	e0:SetProperty(EFFECT_FLAG_CANNOT_DISABLE)
	e0:SetOperation(s.skill0op)
	c:RegisterEffect(e0)
	-- [CardForge] 技能卡的对局规则改动需人工补写（参考 proc_skill.lua）
end
s.listed_series={0x1001, 0x2}
