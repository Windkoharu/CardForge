--[==[ 乱码/\:*?
     CardForge 2.0 生成 · 卡种=融合灵摆（frame=fusion_pendulum） · tier=1
     由效果 IR 投影而来；效果种类缺失的部分以 -- [CardForge] 注释标出。
     ⚑ 融合素材为空，未生成 Fusion.AddProcMix
     ⚑ 效果 kind=不存在的种类 已降级：kind 不在效果注册表里
]==]
local s,id=GetID()
function s.initial_effect(c)
	--灵摆召唤流程（左右刻度编码在 cdb 的 level 字段里，脚本不用写）
	Pendulum.AddProcedure(c)
	--融合素材条件
	-- [CardForge] 融合素材条件为空：请在「召唤条件」里填写素材，未生成 Fusion.AddProcMix
	-- [CardForge] 效果 kind=不存在的种类 暂无脚本片段，需人工补写：kind 不在效果注册表里
	-- 原卡文：①：乱码 ñ中文
end
s.listed_series={0x9, 0x63}
