var doc_window = undefined;

$(function() {
    $(".nav-url-form").submit(function() {
        var prefix = $(this).attr("data-path-prefix");
        var url = $("#theurl").val();
        
        if (doc_window != window.top) {
            prefix += "mp_/";
        }
        
        if (url != '') {
            doc_window.location.href = prefix + url;
        }
        return false;
    });
    
    if (window == window.top && window.frames.length) {
        doc_window = document.getElementById("replay_iframe").contentWindow;
    } else {
        doc_window = window.top;
    }
    
    if (!window.wbinfo) {
        return;
    }
    
    if (window.wbinfo.state) {
        var cls = {"record": "btn-primary",
                   "replay": "btn-success",
                   "patch": "btn-info",
                   "live": "btn-default"};
        
        $("#curr-state").addClass(cls[window.wbinfo.state]);
        
        var label = $(".state-drop #" + window.wbinfo.state).text();
        
        $("#curr-state span.display-badge").text(label);
    }
    
    update_page(window.wbinfo.url, window.wbinfo.timestamp);
    
    if (window.wbinfo.url) {
        $("#theurl").attr("value", window.wbinfo.url);
        $("#theurl").attr("title", window.wbinfo.url);
    }
    
    if (window.wbinfo.info) {
        set_info(window.wbinfo.info);
    }
    
    if (window.wbinfo.state == "record" || window.wbinfo.state == "patch") {
        setInterval(update_info, 10000);
    }
    
    if (window.wbinfo.state == "record") {
        $("#status-rec").show();
    }   
});

function update_page(the_url, timestamp)
{
    if (timestamp && (window.wbinfo.state == "replay" || window.wbinfo.state == "patch")) {
        $("#capture-text").removeClass("hidden");
        $("#capture-text").text("from " + ts_to_date(timestamp));
    }
    
    var prefix = "/" + window.wbinfo.coll + "/";
    
    if (timestamp) {
        timestamp += "/";
    }
    
    $(".state-drop #record").attr("href", prefix + "record/" + the_url);
    $(".state-drop #replay").attr("href", prefix + timestamp + the_url);
    $(".state-drop #patch").attr("href", prefix + "patch/" + timestamp + the_url);
    $(".state-drop #live").attr("href", prefix + "live/" + the_url);
    

    if (doc_window && doc_window.wbinfo) {
        if (doc_window.wbinfo.metadata && doc_window.wbinfo.metadata["snapshot"] == "html") {
            $("#snapshot-label").show();
        } else {
            $("#snapshot").show();
        }
    }
    
//    setTimeout(function() {
//        $("#replay_iframe").css("display", "none");
//    }, 5000);
//    
//    setTimeout(function() {
//        $("#replay_iframe").css("display", "block");
//    }, 5010);
}

function ts_to_date(ts)
{
    if (ts.length < 14) {
        return ts;
    }

    var datestr = (ts.substring(0, 4) + "-" + 
                   ts.substring(4, 6) + "-" +
                   ts.substring(6, 8) + "T" +
                   ts.substring(8, 10) + ":" +
                   ts.substring(10, 12) + ":" +
                   ts.substring(12, 14) + "-00:00");

    return new Date(datestr).toLocaleString();
}

function add_page(capture_url)
{
//    if (window == window.top && window.frames.length) {
//        doc_window = document.getElementById("replay_iframe").contentWindow;
//    } else {
//        doc_window = window.top;
//    }
    
    if (!doc_window.wbinfo) {
        return;
    }
    
    var http = new XMLHttpRequest();
    http._no_rewrite = true;
    
    var post_url = "/_addpage?coll=" + doc_window.wbinfo.coll;

    if (!capture_url) {
        capture_url = doc_window.wbinfo.url;
    }
    
    var params = "url=" + capture_url;

    if (doc_window.document.title) {
        params += "&title=" + doc_window.document.title;
    }

    http.open("POST", post_url);

    //Send the proper header information along with the request
    http.setRequestHeader("Content-type", "application/x-www-form-urlencoded");
    //http.setRequestHeader("Content-length", params.length);
    //http.setRequestHeader("Connection", "close");
    http.send(params);
    
    update_info();
}

// Prevent multiple calls
var is_updating = false;

function update_info()
{
    if (is_updating || !doc_window || !doc_window.wbinfo) {
        return;
    }
    
    is_updating = true;
    
    $.ajax("/_info?coll=" + doc_window.wbinfo.coll, {
        success: function(data) {
            set_info(data);
        }
    }).done(function() {
        is_updating = false;
    });
}

var last_size = undefined;

function set_info(data)
{
    if (!data.user_total_size && !data.total_size) {
        $("#status-rec").hide();
        return;
    }
    
    var total_size = format_bytes(data.total_size);

    var user_total_size = format_bytes(data.user_total_size);
    
    var info = "Collection: " + total_size + ", All Collections: " + user_total_size;
    
    var total_int = parseInt(data.user_total_size);
    var max_int = parseInt(data.user_max_size);
    
    var msg = "";
    
    if (total_int >= max_int) {
        msg = "&nbsp; Size Limit Reached -- Not Recording";
        //$("#status-text").parent().removeClass("label-primary label-warning").addClass("label-danger");
        $(".pulse").hide();
    } else if (total_int >= max_int * 0.95) {
        msg = "&nbsp; Close to Size Limit";
        //$("#status-text").parent().removeClass("label-primary label-danger").addClass("label-warning");
    } else {
        msg = "";
        //$("#status-text").parent().removeClass("label-danger label-warning").addClass("label-primary");
    }

    $("#status-text").html(total_size + msg);
    $("#status-text").attr("title", info);
    
    if (last_size != undefined && total_size > last_size) {
        $("#status-rec").show();
    } else {
        $("#status-rec").hide();
    }
    last_size = total_size;
}

//From http://stackoverflow.com/questions/4498866/actual-numbers-to-the-human-readable-values
function format_bytes(bytes) {
    if (!isFinite(bytes) || (bytes < 1)) {
        return "0 bytes";
    }
    var s = ['bytes', 'KB', 'MB', 'GB', 'TB', 'PB'];
    var e = Math.floor(Math.log(bytes) / Math.log(1000));
    return (bytes / Math.pow(1000, e)).toFixed(2) + " " + s[e];
}

$(function() {
    $("#report-modal").on('show.bs.modal', function() {
        $("#report-form-submit").text("Send Report");
        $("#report-thanks").text("");
        $('#report-form-submit').prop('disabled', false);
    });
    
    $("#report-form").submit(function(e) {
        //$("#report-form-submit").text("Sending Report...");
        
        var params = $("#report-form").serialize();
        
        params += "&" + $.param({coll: wbinfo.coll,
                                 state: wbinfo.state,
                                 url: doc_window.location.href});
        
        $.post("/_reportissues", params, function() {
            $("#report-form-submit").text("Report Sent!");
            $("#report-thanks").text("Thank you for testing webrecorder.io beta!");
            $('#report-form-submit').prop('disabled', true);
            
            setTimeout(function() {
                $("#report-modal").modal('hide');
            }, 1000);
        });
        e.preventDefault();
    });
    
    function apply_iframes(win, func) {
        try {
            func(win);
        } catch (e) {
            console.warn(e);
            return;
        }
        
        for (var i = 0; i < win.frames.length; i++) {
            apply_iframes(win.frames[i], func);
        }
    }
    
    
    $("#snapshot").click(function() {
        var main_window = document.getElementById("replay_iframe").contentWindow;
        
        var wbinfo = window.wbinfo;
        var curr_state = window.curr_state;
        
        function snapshot(win) {
            
            if (win.frameElement && !win.frameElement.getAttribute("src")) {
                console.log("Skipping Snapshot for empty iframe: " + win.location.href);
                return;
            }
            
            var url = win.WB_wombat_location.href;
            
            var params = $.param({coll: wbinfo.coll,
                                  url: url,
                                  title: win.document.title,
                                  addpage: main_window == win,
                                  prefix: wbinfo.prefix});

            //var content = "<!DOCTYPE html>" + win.document.documentElement.outerHTML;
            var s = new XMLSerializer();
            var content = s.serializeToString(win.document);

            $.ajax({
                type: "POST",
                url: "/_snapshot?" + params,
                data: content,
                success: function() {
                    console.log("Saved");
                    $("#snapshot").prop("disabled", false);
                },
                error: function() {
                    console.log("err");
                },
                dataType: 'html',
            });
        }
        
        $("#snapshot").prop("disabled", true);
        
        apply_iframes(main_window, snapshot);
    });
    
//    $(".state-drop a").click(function(e) {
//        e.preventDefault();
//        
//        var new_state = $(e.target).attr("data-state");
//        if (new_state == window.wbinfo.state) {
//            return;
//        }
//        
//        var url = $("#theurl").val();
//        
//        if (!url) {
//            return;
//        }
//        
//        var prefix = "/" + window.wbinfo.coll;
//        
//        if (new_state == "replay") {
//            prefix += "/"
//        } else {
//            prefix += "/" + new_state + "/";
//        }
//        
//        window.location.href = prefix + url;
//    });
});

