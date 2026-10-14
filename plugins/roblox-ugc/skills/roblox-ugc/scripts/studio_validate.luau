local function validate(options)
	local root = options.root
	local kind = options.kind or "rigid"
	local result = {
		stage = "studio-preflight",
		asset_kind = kind,
		checks = {},
		marketplace_approved = false,
		moderation_checked = false,
		visual_fit_checked = false,
	}
	local source = "https://create.roblox.com/docs/marketplace/validation-system"
	local function add(name, status, evidence, url)
		table.insert(result.checks, {check = name, status = status, evidence = evidence, source = url or source})
	end
	if typeof(root) ~= "Instance" then
		add("input-instance", "FAIL", "Supply options.root as the actual imported asset Instance.")
		return result
	end
	result.instance_path = root:GetFullName()
	local forbidden = {}
	local meshes = {}
	local descendants = root:GetDescendants()
	if root:IsA("MeshPart") then
		table.insert(meshes, root)
	end
	for _, item in descendants do
		if item:IsA("LuaSourceContainer") then
			table.insert(forbidden, item:GetFullName())
		elseif item:IsA("MeshPart") then
			table.insert(meshes, item)
		end
	end
	add("extraneous-scripts", #forbidden == 0 and "PASS" or "FAIL", forbidden)
	for _, mesh in meshes do
		add(mesh.Name .. ":opacity", mesh.Transparency == 0 and "PASS" or "WARN", mesh.Transparency)
		add(mesh.Name .. ":material", mesh.Material == Enum.Material.Plastic and "PASS" or "WARN", mesh.Material.Name)
	end
	if kind == "rigid" or kind == "layered" then
		add("accessory-instance", root:IsA("Accessory") and "PASS" or "FAIL", root.ClassName)
		local handle = root:FindFirstChild("Handle")
		add("handle", handle and handle:IsA("MeshPart") and "PASS" or "FAIL", handle and handle.ClassName or "missing")
		if root:IsA("Accessory") then
			add("accessory-type", root.AccessoryType ~= Enum.AccessoryType.Unknown and "PASS" or "FAIL", root.AccessoryType.Name)
		end
		if handle then
			local attachments = {}
			for _, child in handle:GetChildren() do
				if child:IsA("Attachment") then
					table.insert(attachments, child.Name)
				end
			end
			add("attachment-present", #attachments > 0 and "PASS" or "FAIL", attachments)
			if kind == "layered" then
				local wrap = handle:FindFirstChildWhichIsA("WrapLayer")
				add("wrap-layer", wrap and "PASS" or "FAIL", wrap and wrap:GetFullName() or "missing")
			end
		end
	end
	add("visual-fit", "NOT_CHECKED", "Inspect actual body shapes, layering, animations and face expressions through AFT/Avatar Setup/play tests.")
	local runService = game:GetService("RunService")
	if not runService:IsStudio() or not runService:IsRunning() then
		add("official-ugc-validation", "NOT_CHECKED", "Requires a Studio play session with a Player and correctly shaped API input.")
		return result
	end
	local player = options.player or game:GetService("Players"):GetPlayers()[1]
	if not player then
		add("official-ugc-validation", "NOT_CHECKED", "No Player is available in the Studio play session.")
		return result
	end
	local service = game:GetService("AvatarCreationService")
	local supported = kind == "rigid" or kind == "layered" or kind == "body" or kind == "body-part" or kind == "head"
	if not supported then
		add("official-ugc-validation", "NOT_CHECKED", "Use this category's publishing/validation UI; this harness does not claim a universal validator.")
		return result
	end
	local ok, passed, messages = pcall(function()
		if kind == "rigid" or kind == "layered" then
			local accessoryType = options.accessoryType
			if not accessoryType and root:IsA("Accessory") then
				accessoryType = root.AccessoryType
			end
			assert(accessoryType, "Supply options.accessoryType or an Accessory with its type set.")
			return service:ValidateUGCAccessoryAsync(player, root, accessoryType)
		elseif kind == "body" then
			local description = options.humanoidDescription
			if not description and root:IsA("HumanoidDescription") then
				description = root
			end
			assert(description and description:IsA("HumanoidDescription"), "Full-body validation requires a HumanoidDescription with BodyPartDescription child instances.")
			return service:ValidateUGCFullBodyAsync(player, description)
		else
			local bodyPart = options.bodyPart or (kind == "head" and Enum.BodyPart.Head)
			assert(bodyPart, "Supply options.bodyPart and the documented body-part folder structure.")
			return service:ValidateUGCBodyPartAsync(player, root, bodyPart)
		end
	end)
	if not ok then
		add("official-ugc-validation", "NOT_CHECKED", tostring(passed))
	else
		add("official-ugc-validation", passed and "PASS" or "FAIL", {passed = passed, messages = messages}, "https://create.roblox.com/docs/reference/engine/classes/AvatarCreationService")
	end
	return result
end

return validate
