--[==[ 乱码/\:*?
     CardForge 2.0 生成 · 卡种=超量（frame=xyz） · tier=1
     由效果 IR 投影而来；效果种类缺失的部分以 -- [CardForge] 注释标出。
     ⚑ 效果 kind=不存在的种类 已降级：kind 不在效果注册表里
]==]
local s,id=GetID()
function s.initial_effect(c)
	--超量素材条件：13 阶 ×2
	Xyz.AddProcedure(c,nil,13,2)
	c:EnableReviveLimit()
	-- [CardForge] 效果 kind=不存在的种类 暂无脚本片段，需人工补写：kind 不在效果注册表里
	-- 原卡文：①：乱码 ñ中文
end
s.listed_series={0x9, 0x63}
