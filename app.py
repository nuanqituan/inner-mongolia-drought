import streamlit as st
import leafmap.foliumap as leafmap
import geopandas as gpd
import rioxarray
import xarray as xr
import os

# ==========================================
# 1. 基础设置
# ==========================================
st.set_page_config(page_title="内蒙古干旱监测系统", layout="wide")
st.title("内蒙古干旱监测与预警系统")

# ==========================================
# 2. 数据连接配置 (改为本地直读模式)
# ==========================================
# 既然你的 app.py 和 data 文件夹在同一个仓库里
# Streamlit Cloud 会自动把它们下载到服务器的本地硬盘
# 我们直接用 "相对路径"，速度最快，且不需要用户名

DATA_PATH = "data"  # 你的数据文件夹名字

# 矢量文件路径
LEAGUE_PATH = f"{DATA_PATH}/inner_mongolia_city.json"      
BANNER_PATH = f"{DATA_PATH}/inner_mongolia_banners.json"   
BOUNDARY_PATH = f"{DATA_PATH}/inner_mongolia_boundary.json" 

@st.cache_data
def load_data():
    # 检查本地文件是否存在，方便调试
    if not os.path.exists(LEAGUE_PATH):
        return None, None
        
    try:
        leagues_gdf = gpd.read_file(LEAGUE_PATH)
        banners_gdf = gpd.read_file(BANNER_PATH)
        return leagues_gdf, banners_gdf
    except Exception as e:
        return None, None

leagues_gdf, banners_gdf = load_data()

if leagues_gdf is None or banners_gdf is None:
    st.error(f"❌ 本地数据加载失败！\n请检查你的 GitHub 仓库里是否有 'data' 文件夹，且里面有 inner_mongolia_city.json 等文件。")
    # 打印当前目录文件，帮你找错
    st.write("当前目录下的文件:", os.listdir("."))
    if os.path.exists("data"):
        st.write("data 文件夹下的文件:", os.listdir("data")[:5]) # 只显示前5个
    st.stop()

# ==========================================
# 3. 左侧控制面板
# ==========================================
st.sidebar.header("🕹️ 参数选择")

# --- A. 区域选择 ---
league_names = sorted(leagues_gdf['name'].unique())
selected_league = st.sidebar.selectbox("📍 选择盟市", ["全区概览"] + list(league_names))

selected_geom = None
zoom_level = 5
center = [44.0, 115.0]

if selected_league != "全区概览":
    league_feature = leagues_gdf[leagues_gdf['name'] == selected_league]
    selected_geom = league_feature.unary_union
    
    filtered_banners = banners_gdf[banners_gdf['ParentCity'] == selected_league]
    banner_names = sorted(filtered_banners['name'].unique())
    
    selected_banner = st.sidebar.selectbox("🚩 选择旗县 (可选)", ["全盟市"] + list(banner_names))
    
    if selected_banner != "全盟市":
        target_feature = filtered_banners[filtered_banners['name'] == selected_banner]
        if not target_feature.empty:
            selected_geom = target_feature.geometry.iloc[0]
            centroid = target_feature.geometry.centroid
            center = [centroid.y.values[0], centroid.x.values[0]]
            zoom_level = 8
    else:
        centroid = league_feature.geometry.centroid
        center = [centroid.y.values[0], centroid.x.values[0]]
        zoom_level = 6

# --- B. 时间选择 ---
st.sidebar.markdown("---")
scale_display = st.sidebar.selectbox("📊 SPEI 尺度", ["1个月 (气象干旱)", "3个月 (农业干旱)", "12个月 (水文干旱)"])
scale_map = {"1个月 (气象干旱)": "01", "3个月 (农业干旱)": "03", "12个月 (水文干旱)": "12"}
sel_scale = scale_map[scale_display]

sel_year = st.sidebar.slider("📅 年份", 1950, 2025, 2024)
sel_month = st.sidebar.select_slider("🗓️ 月份", range(1, 13), 8)

# 构造本地文件路径
month_str = f"{sel_month:02d}"
tif_file = f"{DATA_PATH}/SPEI_{sel_scale}_{sel_year}_{month_str}.tif"

# ==========================================
# 4. 地图展示核心逻辑
# ==========================================
st.subheader(f"分析视图: {selected_league} - {sel_year}年{sel_month}月")

m = leafmap.Map(center=center, zoom=zoom_level)
vis_params = {'min': -3.0, 'max': 3.0, 'palette': 'RdBu'}

# 1. 显示内蒙古轮廓
try:
    m.add_geojson(BOUNDARY_PATH, layer_name="内蒙古轮廓", style={"fillOpacity": 0, "color": "#333333", "weight": 2})
except:
    pass 

# 2. 加载数据
# 检查文件是否存在
if not os.path.exists(tif_file):
    st.warning(f"⚠️ 找不到该月份的数据文件: {tif_file}")
else:
    try:
        # 使用 rioxarray 读取本地文件 (速度极快)
        xds = rioxarray.open_rasterio(tif_file)
        
        # 【去红操作】过滤无效背景 (小于-10变透明)
        xds = xds.where(xds > -10)
        
        # 如果选了区域，进行裁剪
        if selected_geom is not None:
             xds = xds.rio.clip([selected_geom], crs="EPSG:4326", drop=True)
             # 高亮边框
             m.add_gdf(gpd.GeoDataFrame(geometry=[selected_geom], crs="EPSG:4326"), 
                      layer_name="选中区域边界", style={"fillOpacity": 0, "color": "blue", "weight": 2})

        # 显示数据侦探
        try:
            valid_min = float(xds.min())
            valid_max = float(xds.max())
            st.sidebar.success(f"🔍 数据侦探:\nMin: {valid_min:.2f} | Max: {valid_max:.2f}")
        except:
            pass

        # 保存临时文件用于展示
        # 这一步是为了让 leafmap 读取处理过(去红)的数据
        temp_file = "temp_display.tif"
        xds.rio.to_raster(temp_file)
        
        m.add_raster(temp_file, layer_name="干旱监测数据", **vis_params)

    except Exception as e:
        st.error(f"数据处理出错: {e}")

m.to_streamlit(height=650)