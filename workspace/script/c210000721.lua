--[==[ 乱码/\:*?
     CardForge 2.0 生成 · 卡种=灵摆（frame=pendulum） · tier=1
     由效果 IR 投影而来；效果种类缺失的部分以 -- [CardForge] 注释标出。
     ⚑ 效果 kind=frag_destroy 已降级：kind 不在效果注册表里
]==]
local s,id=GetID()
function s.initial_effect(c)
	--灵摆召唤流程（左右刻度编码在 cdb 的 level 字段里，脚本不用写）
	Pendulum.AddProcedure(c)
	-- [CardForge] 效果 kind=frag_destroy 暂无脚本片段，需人工补写：kind 不在效果注册表里
	-- 原卡文：①：乱码 ñ中文
end
