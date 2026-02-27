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
        #map { width: 100%; height: 100%; }
    </style>
</head>
<body>
    <div id="map"></div>

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
                var geocoder = new kakao.maps.services.Geocoder();
                
                geocoder.addressSearch(addr, function(result, status) {
                    if (status === kakao.maps.services.Status.OK) {
                        var position = new kakao.maps.LatLng(result[0].y, result[0].x);
                        
                        var map = new kakao.maps.Map(mapContainer, {center: position, level: 2});
                        map.setMapTypeId(kakao.maps.MapTypeId.HYBRID);
                        new kakao.maps.Marker({position: position, map: map});
                    } else {
                        mapContainer.innerHTML = "<div style='padding:20px;'><b>주소를 찾을 수 없습니다:</b><br>" + addr + "</div>";
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
