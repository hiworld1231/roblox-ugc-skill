-- Read-only environment diagnosis. Returns a function; never changes the DataModel.
local function doctor(options)
	if options == nil then
		options = {}
	end
	local result = {
		stage = "studio-environment-readiness",
		checks = {},
		asset_checked = false,
		official_validation_executed = false,
		visual_fit_checked = false,
		marketplace_approved = false,
	}
	local source = "https://create.roblox.com/docs/studio/mcp"
	local function add(name, status, evidence, url)
		table.insert(result.checks, {check = name, status = status, evidence = evidence, source = url or source})
	end
	if type(options) ~= "table" then
		add("options", "FAIL", "Supply a table of options or omit it.")
		return result
	end
	local runService = game:GetService("RunService")
	result.environment = {
		studio = runService:IsStudio(),
		running = runService:IsRunning(),
		client = runService:IsClient(),
		server = runService:IsServer(),
		place_id = game.PlaceId,
		engine_version = version(),
	}
	add("studio-runtime", result.environment.studio and "PASS" or "FAIL", result.environment)
	if options.expectedPlaceId ~= nil then
		add("target-place", options.expectedPlaceId == game.PlaceId and "PASS" or "FAIL", {
			expected = options.expectedPlaceId,
			actual = game.PlaceId,
		})
	else
		add("target-place", "NOT_CHECKED", "Caller must identify the intended Studio window/file before mutation; an unsaved place can have PlaceId 0.")
	end
	local serviceOk, avatarService = pcall(function()
		return game:GetService("AvatarCreationService")
	end)
	add("avatar-creation-service", serviceOk and "PASS" or "NOT_CHECKED", serviceOk and "Service exists; no validation method was invoked." or tostring(avatarService), "https://create.roblox.com/docs/reference/engine/classes/AvatarCreationService")
	if serviceOk then
		for _, method in {"ValidateUGCAccessoryAsync", "ValidateUGCBodyPartAsync", "ValidateUGCFullBodyAsync"} do
			local ok, value = pcall(function()
				return avatarService[method]
			end)
			add(method .. ":availability", ok and type(value) == "function" and "WARN" or "NOT_CHECKED", ok and type(value) == "function" and "Method is discoverable. Correct category input, permissions and a successful actual call remain untested." or (ok and "Method is not callable in this environment." or tostring(value)), "https://create.roblox.com/docs/reference/engine/classes/AvatarCreationService")
		end
	end
	local playerCount = #game:GetService("Players"):GetPlayers()
	add("validation-play-prerequisites", result.environment.studio and result.environment.running and playerCount > 0 and "WARN" or "NOT_CHECKED", {
		studio = result.environment.studio,
		running = result.environment.running,
		player_count = playerCount,
		explanation = "This checks prerequisites only. Run studio_validate.luau on the actual imported asset in an appropriate play context for API results.",
	}, "https://create.roblox.com/docs/reference/engine/classes/AvatarCreationService")
	if options.root ~= nil then
		if typeof(options.root) == "Instance" then
			add("asset-reference", "PASS", {class = options.root.ClassName, path = options.root:GetFullName(), explanation = "Reference resolved only; structure, textures, scale and deformation were not checked."})
		else
			add("asset-reference", "FAIL", "options.root must be the actual imported Instance, not a path string or invented ID.")
		end
	else
		add("asset-reference", "NOT_CHECKED", "No imported asset supplied. Environment readiness does not establish asset readiness.")
	end
	local providedTools = options.tool_names
	if providedTools ~= nil and type(providedTools) ~= "table" then
		add("mcp-tool-inventory", "FAIL", "options.tool_names must contain tool names discovered from the current client's actual tool list.")
	else
		local available = {}
		for _, name in providedTools or {} do
			if type(name) == "string" then
				available[name] = true
			end
		end
		for _, name in {"list_roblox_studios", "get_studio_state", "search_game_tree", "inspect_instance", "execute_luau", "screen_capture", "start_stop_play"} do
			add("mcp-tool:" .. name, available[name] and "PASS" or "NOT_CHECKED", available[name] and "Client reports this tool is exposed; individual operations are not tested by this script." or "Tool was not reported by the client. Discover its current tools before choosing an integration.")
		end
	end
	add("native-import-and-avatar-ui", "NOT_CHECKED", "Doctor cannot operate native File > Import, AFT, Avatar Setup, file dialogs or publishing menus. Verify a separate authorized desktop-control integration, or provide the manual handoff.")
	add("marketplace-publish", "NOT_CHECKED", "No upload, payment, moderation or sale operation has been attempted.", "https://create.roblox.com/docs/marketplace/publish-to-marketplace")
	return result
end

return doctor
