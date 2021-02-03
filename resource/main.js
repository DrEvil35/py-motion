var stream_cap = new jsGraphics("frame");

var rect = {x:0, y:0, w:0, h:0};
rect.clear = function(){
	this.x =0;
	this.y =0;
	this.h =0;
	this.w =0;
};
rect.size = function(){
	return this.w * this.h;
};

rect.toArray = function(){
	var arr = [];
	arr.push(this.x);
	arr.push(this.y);
	arr.push(this.w);
	arr.push(this.h);
	return arr;
}

function draw(rect, offsetX = 0, offsetY = 0){
	stream_cap.clear();
	stream_cap.setColor("#ff0000");
	stream_cap.drawRect(rect.x+offsetX,rect.y+offsetY, rect.w,rect.h);
	stream_cap.paint();
	
}

function setButton(p){
	if(p){
		$("#detector").text("Выключить детектор");
		$("#refresh_detector").prop("disabled",false);
	}else{
		$("#detector").text("Включить детектор");
		$("#refresh_detector").prop("disabled",true);
		stream_cap.clear();
	}
}
function send_detector_property(arg){
	var post_data = {
		index: $("#capture").attr("cam"),
		method: "detection",
		sens : $("#sens_range").val(),
	};
	if(arg && "type" in arg){
		post_data.type = arg.type
	}
	if (rect.size() > 1){
		post_data.area = rect.toArray();
	}
	console.log("detector post data", post_data);
	$.post("/cam",post_data, 
		function(data){
			if (data){
				try{
					var js_obj = JSON.parse(data);
				}catch(e) {
					console.log(e);
					return;
				}
				if (arg && "refresh" in arg && arg.refresh == false){
					return;
				}
				setButton(js_obj.state == "on");
			}
	  		
		});
}

var load_state = function(){
	var get_data = {
		index: $("#capture").attr("cam"),
		method: "state"
	};
	
	$.get("/cam",get_data,function(data){
		if(data){
			try{
				var js_obj = JSON.parse(data);
			}catch(e) {
				console.log(e);
				return;
			}
			console.log(js_obj)
			if ("detector" in js_obj){
				setButton(true);
				rectangle = js_obj.detector.area;
				pos_frame = $("#frame").position();
				draw(rectangle,pos_frame.left, pos_frame.top);
			}else{
				setButton(false);
				stream_cap.clear();
			}
		}
	});
}

$(window).error(function(){
	alert("olololo");
})

$(window).focus(load_state);
$(window).load(load_state);

$('#frame').mousedown(function(e) {
	stream_cap.clear();
	rect.clear();
	rect.x = e.pageX-$(this).offset().left;
	rect.y = e.pageY-$(this).offset().top;
	$(this).mousemove(function(e){
		
		rect.w = e.pageX- $(this).offset().left - rect.x;
		rect.h = e.pageY-$(this).offset().top - rect.y;
		draw(rect,$(this).position().left, $(this).position().top);
	});
	
	$(this).mouseup(function(e){
		$(this).off("mousemove");
	})
});

downloadSnapshot = function(){
	var link = document.createElement('a');
	link.href = 'cam?index='+$("#capture").attr("cam")+"&method=snapshot";
	document.body.appendChild(link);
	link.click();
}

$("#capture").dblclick(function(){
	downloadSnapshot();
})

$("#make_shot").click(function(){
	downloadSnapshot();
})

$("#detector").click(function(e){
	send_detector_property();
});

$("#refresh_detector").click(function(e){
	send_detector_property({type : "on", refresh : false})
})
