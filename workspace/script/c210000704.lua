--[==[ c210000704
     CardForge 2.0 生成 · 卡种=超量（frame=xyz） · tier=1
     由效果 IR 投影而来；效果种类缺失的部分以 -- [CardForge] 注释标出。
]==]
local s,id=GetID()
function s.initial_effect(c)
	--超量素材条件：0 阶 ×2
	Xyz.AddProcedure(c,nil,0,2)
	c:EnableReviveLimit()
end
s.listed_series={0x9, 0x63}
