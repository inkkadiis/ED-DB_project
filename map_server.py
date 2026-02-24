"""
간단한 Flask 서버로 map.html을 제공
Streamlit과 함께 실행하여 iframe에서 올바른 origin 제공
"""
from flask import Flask, request, render_template_string
import os
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

MAP_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        html, body { width: 100%; height: 100%; margin: 0; padding: 0; overflow: hidden; font-family: sans-serif; }
        #mapWrapper, #rvWrapper { width: 100%; height: 100%; position: absolute; top: 0; left: 0; }
        #btnToggle { position: absolute; top: 15px; right: 15px; z-index: 10; padding: 10px 15px; font-weight: bold; border-radius: 5px; border: 2px solid #333; background-color: #fff; cursor: pointer; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
    </style>
</head>
<body>
    <div id="mapWrapper" style="z-index: 1;"><div id="map" style="width:100%; height:100%;"></div></div>
    <div id="rvWrapper" style="z-index: 0; visibility: hidden;"><div id="roadview" style="width:100%; height:100%;"></div></div>
    <button id="btnToggle">🔄 로드뷰 보기</button>

    <script>
        const addr = "{{ addr }}";
        const key = "{{ key }}";
        
        var script = document.createElement('script');
        script.type = 'text/javascript';
        script.src = 'https://dapi.kakao.com/v2/maps/sdk.js?appkey=' + key + '&libraries=services&autoload=false';
        document.head.appendChild(script);

        script.onload = function() {
            kakao.maps.load(function() {
                var mapContainer = document.getElementById('map');
                var rvContainer = document.getElementById('roadview');
                var mapWrapper = document.getElementById('mapWrapper');
                var rvWrapper = document.getElementById('rvWrapper');
                var btnToggle = document.getElementById('btnToggle');
                var isRoadview = false;

                var geocoder = new kakao.maps.services.Geocoder();
                geocoder.addressSearch(addr, function(result, status) {
                    if (status === kakao.maps.services.Status.OK) {
                        var position = new kakao.maps.LatLng(result[0].y, result[0].x);
                        
                        var map = new kakao.maps.Map(mapContainer, {center: position, level: 2});
                        map.setMapTypeId(kakao.maps.MapTypeId.HYBRID);
                        new kakao.maps.Marker({position: position, map: map});

                        var roadview = new kakao.maps.Roadview(rvContainer);
                        var roadviewClient = new kakao.maps.RoadviewClient();

                        btnToggle.onclick = function() {
                            if (!isRoadview) {
                                mapWrapper.style.visibility = 'hidden';
                                rvWrapper.style.visibility = 'visible';
                                btnToggle.innerText = '🗺️ 위성지도로 복귀';
                                roadviewClient.getNearestPanoId(position, 50, function(panoId) {
                                    if (panoId) roadview.setPanoId(panoId, position);
                                    else rvContainer.innerHTML = "<div style='display:flex;align-items:center;justify-content:center;height:100%;'><b>로드뷰 미지원 지역입니다.</b></div>";
                                });
                                isRoadview = true;
                            } else {
                                rvWrapper.style.visibility = 'hidden';
                                mapWrapper.style.visibility = 'visible';
                                btnToggle.innerText = '🔄 로드뷰 보기';
                                isRoadview = false;
                            }
                        };
                    } else {
                        mapContainer.innerHTML = "<div style='padding:20px;'><b>주소를 찾을 수 없습니다:</b><br>" + addr + "</div>";
                        btnToggle.style.display = 'none';
                    }
                });
            });
        };
    </script>
</body>
</html>
"""

@app.route('/map')
def show_map():
    addr = request.args.get('addr', '')
    key = os.getenv('KAKAO_JS_KEY')
    return render_template_string(MAP_TEMPLATE, addr=addr, key=key)

if __name__ == '__main__':
    # Streamlit은 8502에서 실행 중이므로 Flask는 다른 포트 사용
    app.run(host='localhost', port=5001, debug=False)
