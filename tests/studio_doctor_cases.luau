-- Read-only runtime checks. Evaluate both modules, then call runCases(doctor).
return function(doctor)
	local function status(report, name)
		for _, check in report.checks do
			if check.check == name then
				return check.status
			end
		end
		return nil
	end
	local cases = {
		omitted = doctor(),
		actualInventory = doctor({expectedPlaceId = game.PlaceId, tool_names = {"list_roblox_studios", "get_studio_state", "search_game_tree", "inspect_instance", "execute_luau", "screen_capture", "start_stop_play"}}),
		wrongTarget = doctor({expectedPlaceId = -1}),
		wrongRoot = doctor({root = "Workspace.InventedAccessory"}),
		wrongTools = doctor({tool_names = "execute_luau"}),
		invalidOptions = doctor(false),
	}
	assert(status(cases.omitted, "asset-reference") == "NOT_CHECKED", "Missing imported asset must not pass.")
	assert(status(cases.omitted, "mcp-tool:execute_luau") == "NOT_CHECKED", "Missing tool inventory must not pass.")
	assert(status(cases.actualInventory, "target-place") == "PASS", "Current target identity should match.")
	assert(status(cases.actualInventory, "mcp-tool:execute_luau") == "PASS", "A supplied discovery record should be reported as exposed.")
	assert(status(cases.actualInventory, "native-import-and-avatar-ui") == "NOT_CHECKED", "Exposed Luau must not imply native UI control.")
	assert(status(cases.actualInventory, "marketplace-publish") == "NOT_CHECKED", "Read-only diagnosis must not imply publication.")
	assert(status(cases.wrongTarget, "target-place") == "FAIL", "Mismatched target must fail.")
	assert(status(cases.wrongRoot, "asset-reference") == "FAIL", "A path string is not an imported Instance.")
	assert(status(cases.wrongTools, "mcp-tool-inventory") == "FAIL", "Malformed inventory must fail.")
	assert(status(cases.invalidOptions, "options") == "FAIL", "False is not an options table.")
	for _, report in cases do
		assert(report.official_validation_executed == false, "Doctor must not call official validation.")
		assert(report.asset_checked == false, "Doctor must not claim asset validation.")
		assert(report.visual_fit_checked == false, "Doctor must not claim fitting.")
		assert(report.marketplace_approved == false, "Doctor must not claim approval.")
	end
	return {status = "PASS", runtime_assertions = 34, cases = cases}
end
