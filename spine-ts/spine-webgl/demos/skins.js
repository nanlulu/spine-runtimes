var skinsDemo = function (canvas, bgColor) {
	var HIGHLIGHT_COLOR = new spine.Color(1, 0, 0, 1);

	var canvas, gl, renderer, input, assetManager;
	var skeleton, state, offset, bounds;
	var timeKeeper;
	var playButton, timeLine, isPlaying = true, playTime = 0;
	var randomizeSkins, lastSkinChange = Date.now() / 1000, clickAnim = 0;

	if (!bgColor) bgColor = new spine.Color(235 / 255, 239 / 255, 244 / 255, 1);

	function init() {
		gl = canvas.context.gl;
		renderer = new spine.SceneRenderer(canvas, gl);
		assetManager = new spine.AssetManager(gl, spineDemos.path, spineDemos.downloader);
		assetManager.loadTextureAtlas("heroes.atlas");
		assetManager.loadJson("demos.json");
		input = new spine.Input(canvas);
		timeKeeper = new spine.TimeKeeper();
	}

	function loadingComplete() {
		var atlasLoader = new spine.AtlasAttachmentLoader(assetManager.get("heroes.atlas"));
		var skeletonJson = new spine.SkeletonJson(atlasLoader);
		var skeletonData = skeletonJson.readSkeletonData(assetManager.get("demos.json").heroes);
		skeleton = new spine.Skeleton(skeletonData);
		skeleton.setSkinByName("Assassin");
		var stateData = new spine.AnimationStateData(skeleton.data);
		stateData.defaultMix = 0.2;
		stateData.setMix("roll", "run", 0);
		stateData.setMix("jump", "run2", 0);
		state = new spine.AnimationState(stateData);
		setupAnimations(state);
		state.apply(skeleton);
		skeleton.updateWorldTransform(spine.Physics.update);
		offset = new spine.Vector2();
		bounds = new spine.Vector2();
		skeleton.getBounds(offset, bounds, []);
		setupUI();
		setupInput();
	}

	function setupInput() {
		input.addListener({
			down: function (x, y) {
				swingSword();
			},
			up: function (x, y) { },
			dragged: function (x, y) { },
			moved: function (x, y) { }
		});
	}

	function setupAnimations(state) {
		state.addAnimation(0, "idle", true, 1);
		state.addAnimation(0, "walk", true, 2);
		state.addAnimation(0, "run", true, 4);
		state.addAnimation(0, "roll", false, 3);
		state.addAnimation(0, "run", true, 0);
		state.addAnimation(0, "run2", true, 1.5);
		state.addAnimation(0, "jump", false, 3);
		state.addAnimation(0, "run2", true, 0);
		state.addAnimation(0, "run", true, 1);
		state.addAnimation(0, "idle", true, 3);
		state.addAnimation(0, "idleTired", true, 0.5);
		state.addAnimation(0, "idle", true, 2);
		state.addAnimation(0, "walk2", true, 1);
		state.addAnimation(0, "block", true, 3);
		state.addAnimation(0, "punch1", false, 1.5);
		state.addAnimation(0, "block", true, 0);
		state.addAnimation(0, "punch1", false, 1.5);
		state.addAnimation(0, "punch2", false, 0);
		state.addAnimation(0, "block", true, 0);
		state.addAnimation(0, "hitBig", false, 1.5);
		state.addAnimation(0, "floorIdle", true, 0);
		state.addAnimation(0, "floorGetUp", false, 1.5);
		state.addAnimation(0, "idle", true, 0);
		state.addAnimation(0, "meleeSwing1-fullBody", false, 1.5);
		state.addAnimation(0, "idle", true, 0);
		state.addAnimation(0, "meleeSwing2-fullBody", false, 1.5);
		state.addAnimation(0, "idle", true, 0);
		state.addAnimation(0, "idleTired", true, 0.5);
		state.addAnimation(0, "crouchIdle", true, 1.5);
		state.addAnimation(0, "crouchWalk", true, 2);
		state.addAnimation(0, "crouchIdle", true, 2.5).listener = {
			start: function (trackIndex) {
				setupAnimations(state);
			}
		};

		state.setAnimation(1, "empty", false, 0);
		state.setAnimation(1, "hideSword", false, 2);
	}

	function setupUI() {
		var list = $("#skins-skin");
		for (var skin in skeleton.data.skins) {
			skin = skeleton.data.skins[skin];
			if (skin.name == "default") continue;
			var option = $("<option></option>");
			option.attr("value", skin.name).text(skin.name);
			if (skin.name === "Assassin") {
				option.attr("selected", "selected");
				skeleton.setSkinByName("Assassin");
			}
			list.append(option);
		}
		list.change(function () {
			activeSkin = $("#skins-skin option:selected").text();
			skeleton.setSkinByName(activeSkin);
			skeleton.setSlotsToSetupPose();
			randomizeSkins.checked = false;
		});

		$("#skins-randomizeattachments").click(randomizeAttachments);
		$("#skins-swingsword").click(swingSword);
		randomizeSkins = document.getElementById("skins-randomizeskins");
	}

	function setSkin(skin) {
		var slot = skeleton.findSlot("item_near");
		var weapon = slot.getAttachment();
		skeleton.setSkin(skin);
		skeleton.setSlotsToSetupPose();
		slot.setAttachment(weapon);
	}

	function swingSword() {
		state.setAnimation(5, (clickAnim++ % 2 == 0) ? "meleeSwing2" : "meleeSwing1", false, 0);
	}

	function randomizeSkin() {
		var result;
		var count = 0;
		for (var skin in skeleton.data.skins) {
			if (skeleton.data.skins[skin].name === "default") continue;
			if (Math.random() < 1 / ++count) {
				result = skeleton.data.skins[skin];
			}
		}
		setSkin(result);
		$("#skins-skin option").filter(function () {
			return ($(this).text() == result.name);
		}).prop("selected", true);
	}

	function randomizeAttachments() {
		var skins = [];
		for (var skin in skeleton.data.skins) {
			skin = skeleton.data.skins[skin];
			if (skin.name === "default") continue;
			skins.push(skin);
		}

		var newSkin = new spine.Skin("random-skin");
		for (var slot = 0; slot < skeleton.slots.length; slot++) {
			var skin = skins[(Math.random() * skins.length - 1) | 0];
			var attachments = skin.attachments[slot];
			for (var attachmentName in attachments) {
				newSkin.setAttachment(slot, attachmentName, attachments[attachmentName]);
			}
		}
		setSkin(newSkin);
		randomizeSkins.checked = false;
	}

	function render() {
		timeKeeper.update();
		var delta = timeKeeper.delta;

		if (randomizeSkins.checked) {
			var now = Date.now() / 1000;
			if (now - lastSkinChange > 2) {
				randomizeSkin();
				lastSkinChange = now;
			}
		}

		renderer.camera.position.x = offset.x + bounds.x * 1.5 - 125;
		renderer.camera.position.y = offset.y + bounds.y / 2;
		renderer.camera.viewportWidth = bounds.x * 3;
		renderer.camera.viewportHeight = bounds.y * 1.2;
		renderer.resize(spine.ResizeMode.Fit);

		gl.clearColor(bgColor.r, bgColor.g, bgColor.b, bgColor.a);
		gl.clear(gl.COLOR_BUFFER_BIT);

		state.update(delta);
		state.apply(skeleton);
		skeleton.updateWorldTransform(spine.Physics.update);

		renderer.begin();
		renderer.drawSkeleton(skeleton, true);
		var texture = assetManager.get("heroes.png");
		var width = bounds.x * 1.25;
		var scale = width / texture.getImage().width;
		var height = scale * texture.getImage().height;
		var texX = offset.x + bounds.x + 190;
		var texY = offset.y + bounds.y / 2 - height / 2 - 5;
		var imgWidth = texture.getImage().width;
		var imgHeight = texture.getImage().height;

		// Draw the full texture sheet dimmed
		var DIM_COLOR = new spine.Color(0.3, 0.3, 0.3, 1);
		renderer.drawTexture(texture, texX, texY, width, height, DIM_COLOR);

		// Collect active regions
		var activeRegions = [];
		var seen = {};
		for (var i = 0; i < skeleton.drawOrder.length; i++) {
			var slot = skeleton.drawOrder[i];
			var attachment = slot.getAttachment();
			if (!attachment || !attachment.region) continue;
			var region = attachment.region;
			var key = region.u + "," + region.v + "," + region.u2 + "," + region.v2;
			if (seen[key]) continue;
			seen[key] = true;
			activeRegions.push(region);
		}

		// Re-draw active regions at full brightness on top of the dimmed sheet
		for (var i = 0; i < activeRegions.length; i++) {
			var region = activeRegions[i];
			var rx = texX + region.u * imgWidth * scale;
			var ry = texY + (1 - region.v2) * imgHeight * scale;
			var rw = (region.u2 - region.u) * imgWidth * scale;
			var rh = (region.v2 - region.v) * imgHeight * scale;
			renderer.drawRegion(region, rx, ry, rw, rh);
		}

		// Draw red outlines around active regions
		for (var i = 0; i < activeRegions.length; i++) {
			var region = activeRegions[i];
			var rx = texX + region.u * imgWidth * scale;
			var ry = texY + (1 - region.v2) * imgHeight * scale;
			var rw = (region.u2 - region.u) * imgWidth * scale;
			var rh = (region.v2 - region.v) * imgHeight * scale;
			var lw = 2;
			renderer.rectLine(true, rx, ry, rx + rw, ry, lw, HIGHLIGHT_COLOR);
			renderer.rectLine(true, rx + rw, ry, rx + rw, ry + rh, lw, HIGHLIGHT_COLOR);
			renderer.rectLine(true, rx + rw, ry + rh, rx, ry + rh, lw, HIGHLIGHT_COLOR);
			renderer.rectLine(true, rx, ry + rh, rx, ry, lw, HIGHLIGHT_COLOR);
		}

		renderer.end();
	}

	init();
	skinsDemo.assetManager = assetManager;
	skinsDemo.loadingComplete = loadingComplete;
	skinsDemo.render = render;
};