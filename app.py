import streamlit as st
from streamlit_option_menu import option_menu
import leafmap.foliumap as leafmap
import geopandas as gpd
import rioxarray
import xarray as xr
import os
import numpy as np
import pandas as pd
import altair as alt
from PIL import Image
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import folium
import time

# ==========================================
# 1. 基础设置与常量
# ==========================================
st.set_page_config(page_title="内蒙古旱涝监测与预警系统", layout="wide")

# 数据路径配置
DATA_PATH = "data"
LEAGUE_PATH = f"{DATA_PATH}/inner_mongolia_city.json"
BANNER_PATH = f"{DATA_PATH}/inner_mongolia_banners.json"
BOUNDARY_PATH = f"{DATA_PATH}/inner_mongolia_boundary.json"

# 坐标校准参数 (向南平移0.5度)
FIX_LAT_OFFSET = -0.5
FIX_LON_OFFSET = 0.0

# ==========================================
# 2. 核心算法函数
# ==========================================
@st.cache_data
def load_data():
    if not os.path.exists(LEAGUE_PATH): return None, None
    try:
        leagues_gdf = gpd.read_file(LEAGUE_PATH)
        banners_gdf = gpd.read_file(BANNER_PATH)
        return leagues_gdf, banners_gdf
    except: return None, None

def calculate_weighted_area(valid_data, lats):
    """
    根据纬度计算加权面积
    valid_data: 有效数据的一维数组
    lats: 对应的纬度数组
    返回: 总面积 (万平方公里)
    """
    # 地球平均半径 R ≈ 6371 km
    # 0.25度对应的弧度
    rad = np.radians(0.25)
    R = 6371.0
    
    # 像元高度 (经线方向) ≈ 111.32 km * 0.25 ≈ 27.83 km
    # pixel_height = R * rad
    
    # 像元宽度 (纬线方向) = R * cos(lat) * rad
    # 单个像元面积 = height * width = (R * rad) * (R * rad * cos(lat))
    # Area ≈ 774.6 * cos(lat) 平方公里
    
    pixel_areas = 774.6 * np.cos(np.radians(lats))
    total_area_sqkm = np.sum(pixel_areas)
    return total_area_sqkm / 10000.0  # 转换为万平方公里

def classify_spei(value):
    if value < -2: return '极端干旱'
    if -2 <= value < -1.5: return '严重干旱'
    if -1.5 <= value < -1: return '中度干旱'
    if -1 <= value <= 1: return '正常'
    if 1 < value <= 1.5: return '中度湿润'
    if 1.5 < value <= 2: return '严重湿润'
    if value > 2: return '极端湿润'
    return '正常'

# ==========================================
# 3. 数据加载
# ==========================================
leagues_gdf, banners_gdf = load_data()

if leagues_gdf is None:
    st.error("❌ 本地数据未找到,请检查 data 文件夹。")
    st.stop()

# ==========================================
# 4. 顶部导航栏
# ==========================================
with st.container():
    selected_nav = option_menu(
        menu_title=None,
        options=["首页", "旱涝监测"],
        icons=["house", "cloud-rain"],
        menu_icon="cast",
        default_index=1,
        orientation="horizontal",
        styles={
            "container": {"padding": "0!important", "background-color": "#f0f2f6"},
            "icon": {"color": "#333", "font-size": "16px"}, 
            "nav-link": {"font-size": "16px", "text-align": "center", "margin": "0px"},
            "nav-link-selected": {"background-color": "#4e8cff"},
        }
    )

# ==========================================
# 5. 页面逻辑
# ==========================================
if selected_nav == "首页":
    st.title("欢迎使用内蒙古旱涝监测与预警系统")
    st.write("请点击顶部 **'旱涝监测'** 选项卡开始使用。")

elif selected_nav == "旱涝监测":
    st.title("内蒙古旱涝监测与预警系统")

    # --- 左侧参数 ---
    st.sidebar.header("🕹️ 参数选择")

    # A. 区域选择
    league_names = sorted(leagues_gdf['name'].unique())
    selected_league = st.sidebar.selectbox("📍 选择盟市", ["全区概览"] + list(league_names))

    selected_geom = None
    zoom_level = 5
    center = [44.0, 115.0]
    region_name = "内蒙古全区"
    sub_regions_gdf = leagues_gdf # 默认下级区域是盟市

    if selected_league != "全区概览":
        league_feature = leagues_gdf[leagues_gdf['name'] == selected_league]
        selected_geom = league_feature.unary_union
        region_name = selected_league
        
        # 筛选该盟市下的旗县
        filtered_banners = banners_gdf[banners_gdf['ParentCity'] == selected_league]
        sub_regions_gdf = filtered_banners # 下级区域变为旗县
        
        banner_names = sorted(filtered_banners['name'].unique())
        selected_banner = st.sidebar.selectbox("🚩 选择旗县 (可选)", ["全盟市"] + list(banner_names))
        
        if selected_banner != "全盟市":
            target_feature = filtered_banners[filtered_banners['name'] == selected_banner]
            if not target_feature.empty:
                selected_geom = target_feature.geometry.iloc[0]
                centroid = target_feature.geometry.centroid
                center = [centroid.y.values[0], centroid.x.values[0]]
                zoom_level = 8
                region_name = selected_banner
                sub_regions_gdf = None # 到了最底层，没有下级了
        else:
            centroid = league_feature.geometry.centroid
            center = [centroid.y.values[0], centroid.x.values[0]]
            zoom_level = 6

    # B. 时间选择
    st.sidebar.markdown("---")
    scale_display = st.sidebar.selectbox("📊 SPEI 尺度", ["1个月 (气象旱涝)", "3个月 (农业旱涝)", "12个月 (水文旱涝)"])
    scale_map = {"1个月 (气象旱涝)": "01", "3个月 (农业旱涝)": "03", "12个月 (水文旱涝)": "12"}
    sel_scale = scale_map[scale_display]

    sel_year = st.sidebar.slider("📅 年份", 1950, 2025, 2024)
    sel_month = st.sidebar.select_slider("🗓️ 月份", range(1, 13), 8)

    month_str = f"{sel_month:02d}"
    tif_file = f"{DATA_PATH}/SPEI_{sel_scale}_{sel_year}_{month_str}.tif"

    # --- 布局 ---
    col_map, col_stats = st.columns([3, 1])

    # === 全局变量 ===
    current_stats = {} # 存储当前区域的统计信息
    sub_stats_data = [] # 存储下级区域的列表数据

    # === 1. 地图展示 ===
    with col_map:
        st.subheader(f"🗺️ 分析视图: {region_name}")
        m = leafmap.Map(center=center, zoom=zoom_level, locate_control=False, draw_control=False)

        try:
            m.add_geojson(BOUNDARY_PATH, layer_name="内蒙古轮廓", 
                        style={"fillOpacity": 0, "color": "#333333", "weight": 2})
        except: pass

        if not os.path.exists(tif_file):
            st.warning(f"⚠️ 暂无该月份数据")
        else:
            try:
                # 读取数据
                xds = rioxarray.open_rasterio(tif_file)
                if xds.rio.crs is None: xds = xds.rio.write_crs("EPSG:4326")

                # 裁剪
                if selected_geom is not None:
                    try:
                        xds = xds.rio.clip([selected_geom], crs="EPSG:4326", drop=True)
                        m.add_gdf(gpd.GeoDataFrame(geometry=[selected_geom], crs="EPSG:4326"), 
                                layer_name="选中区域", style={"fillOpacity": 0, "color": "#0066ff", "weight": 3})
                    except: pass

                # 处理数据
                data = xds.values[0]
                # 获取每个像元的纬度 (用于面积计算)
                # rioxarray 坐标通常是 y, x
                height, width = data.shape
                lats = xds.y.values
                # 创建纬度矩阵 (height, width)
                lat_grid = np.repeat(lats[:, np.newaxis], width, axis=1)

                data_clean = np.where(data > -10, data, np.nan)
                valid_mask = ~np.isnan(data_clean)
                
                if np.any(valid_mask):
                    # --- 计算当前视图的面积统计 ---
                    valid_vals = data_clean[valid_mask]
                    valid_lats = lat_grid[valid_mask]
                    
                    # 1. 总面积
                    total_area = calculate_weighted_area(valid_vals, valid_lats)
                    
                    # 2. 各等级面积
                    categories = ['极端干旱', '严重干旱', '中度干旱', '正常', '中度湿润', '严重湿润', '极端湿润']
                    current_stats = {cat: 0.0 for cat in categories}
                    
                    # 向量化计算各等级掩膜
                    masks = {
                        '极端干旱': valid_vals < -2,
                        '严重干旱': (valid_vals >= -2) & (valid_vals < -1.5),
                        '中度干旱': (valid_vals >= -1.5) & (valid_vals < -1),
                        '正常': (valid_vals >= -1) & (valid_vals <= 1),
                        '中度湿润': (valid_vals > 1) & (valid_vals <= 1.5),
                        '严重湿润': (valid_vals > 1.5) & (valid_vals <= 2),
                        '极端湿润': valid_vals > 2
                    }
                    
                    for cat, mask in masks.items():
                        if np.any(mask):
                            area = calculate_weighted_area(valid_vals[mask], valid_lats[mask])
                            current_stats[cat] = area

                    # --- 渲染地图图片 ---
                    cmap = plt.cm.RdBu
                    norm = mcolors.Normalize(vmin=-3, vmax=3)
                    rgba_array = cmap(norm(data_clean))
                    rgba_array[..., 3] = np.where(valid_mask, 1.0, 0.0)
                    
                    img = Image.fromarray((rgba_array * 255).astype(np.uint8), mode='RGBA')
                    temp_png = "temp_spei_vis.png"
                    img.save(temp_png, format='PNG')
                    
                    bounds = xds.rio.bounds()
                    leaflet_bounds = [
                        [bounds[1] + FIX_LAT_OFFSET, bounds[0] + FIX_LON_OFFSET], 
                        [bounds[3] + FIX_LAT_OFFSET, bounds[2] + FIX_LON_OFFSET]
                    ]
                    
                    img_overlay = folium.raster_layers.ImageOverlay(
                        image=temp_png,
                        bounds=leaflet_bounds,
                        opacity=0.85,
                        interactive=True,
                        cross_origin=False,
                        zindex=1,
                        name='SPEI指数'
                    )
                    img_overlay.add_to(m)
                    try: os.remove(temp_png)
                    except: pass
                    
                    # 旱涝等级图例
                    legend_html = '''
                    <div style="position: fixed; bottom: 30px; right: 10px; width: 140px; background: white; z-index:9999; font-size:12px; border:2px solid grey; border-radius: 5px; padding: 10px;">
                        <p style="text-align:center; font-weight:bold; margin:0 0 5px 0;">SPEI旱涝等级</p>
                        <div style="display:flex; justify-content:space-between; margin-bottom:2px;"><span style="background:#ca0020; width:20px;"></span> 极端干旱</div>
                        <div style="display:flex; justify-content:space-between; margin-bottom:2px;"><span style="background:#f4a582; width:20px;"></span> 严重干旱</div>
                        <div style="display:flex; justify-content:space-between; margin-bottom:2px;"><span style="background:#fddbc7; width:20px;"></span> 中度干旱</div>
                        <div style="display:flex; justify-content:space-between; margin-bottom:2px;"><span style="background:#f7f7f7; width:20px; border:1px solid #ccc;"></span> 正常</div>
                        <div style="display:flex; justify-content:space-between; margin-bottom:2px;"><span style="background:#d1e5f0; width:20px;"></span> 中度湿润</div>
                        <div style="display:flex; justify-content:space-between; margin-bottom:2px;"><span style="background:#92c5de; width:20px;"></span> 严重湿润</div>
                        <div style="display:flex; justify-content:space-between;"><span style="background:#0571b0; width:20px;"></span> 极端湿润</div>
                    </div>
                    '''
                    m.get_root().html.add_child(folium.Element(legend_html))

            except Exception as e:
                st.error(f"渲染错误: {e}")

        m.to_streamlit(height=650)

    # === 2. 右侧统计面板 ===
    with col_stats:
        st.markdown(f"### 📊 统计面板")
        if current_stats:
            total_area = sum(current_stats.values())
            st.metric("监测区域总面积", f"{total_area:.2f} 万km²")
            
            # 准备图表数据
            df_chart = pd.DataFrame({
                '等级': list(current_stats.keys()),
                '面积': [round(v, 2) for v in current_stats.values()],
                '颜色': ['#ca0020', '#f4a582', '#fddbc7', '#f7f7f7', '#d1e5f0', '#92c5de', '#0571b0']
            })
            
            chart = alt.Chart(df_chart).mark_bar().encode(
                x=alt.X('面积', title='面积 (万km²)'),
                y=alt.Y('等级', sort=None, title=None),
                color=alt.Color('颜色', scale=None, legend=None),
                tooltip=['等级', '面积']
            ).properties(height=300)
            
            st.altair_chart(chart, use_container_width=True)
            
            # 显示关键干旱数据
            drought_area = current_stats['极端干旱'] + current_stats['严重干旱'] + current_stats['中度干旱']
            st.caption(f"🔥 总干旱面积: {drought_area:.2f} 万km² ({(drought_area/total_area)*100:.1f}%)")

    # === 3. 下级行政区详细统计表 & 智能报告 ===
    st.markdown("---")
    st.subheader(f"📑 {region_name} - 详细旱涝监测报告")
    
    # 只有当有下级区域（且不是最底层旗县）时才计算
    if sub_regions_gdf is not None and not sub_regions_gdf.empty and os.path.exists(tif_file):
        
        # 为了不阻塞页面，使用 expander 或按钮触发（或者直接计算，如果数量不多）
        # 12个盟市很快，100个旗县可能要几秒。这里直接计算并显示进度条。
        
        calc_status = st.empty()
        calc_status.info("正在计算各分辖区面积统计，请稍候...")
        
        progress_bar = st.progress(0)
        
        sub_results = []
        total_sub = len(sub_regions_gdf)
        
        # 重新读取原始数据用于循环裁剪
        xds_raw = rioxarray.open_rasterio(tif_file)
        if xds_raw.rio.crs is None: xds_raw = xds_raw.rio.write_crs("EPSG:4326")
        
        for idx, (_, row) in enumerate(sub_regions_gdf.iterrows()):
            sub_name = row['name']
            sub_geom = row['geometry']
            
            try:
                # 裁剪
                clipped = xds_raw.rio.clip([sub_geom], crs="EPSG:4326", drop=True)
                
                # 计算面积
                data_sub = clipped.values[0]
                lats_sub = clipped.y.values
                height_s, width_s = data_sub.shape
                lat_grid_s = np.repeat(lats_sub[:, np.newaxis], width_s, axis=1)
                
                valid_mask_s = (data_sub > -10) & (~np.isnan(data_sub))
                
                if np.any(valid_mask_s):
                    vals_s = data_sub[valid_mask_s]
                    lats_s = lat_grid_s[valid_mask_s]
                    
                    area_sub = calculate_weighted_area(vals_s, lats_s)
                    
                    # 统计各类面积
                    row_data = {'行政区': sub_name, '总面积(万km²)': round(area_sub, 3)}
                    
                    for cat in ['极端干旱', '严重干旱', '中度干旱', '正常', '中度湿润', '严重湿润', '极端湿润']:
                        # 简化计算：这里可以把 classify_spei 向量化
                        # 为了速度，我们直接用掩膜
                        if cat == '极端干旱': m = vals_s < -2
                        elif cat == '严重干旱': m = (vals_s >= -2) & (vals_s < -1.5)
                        elif cat == '中度干旱': m = (vals_s >= -1.5) & (vals_s < -1)
                        elif cat == '正常': m = (vals_s >= -1) & (vals_s <= 1)
                        elif cat == '中度湿润': m = (vals_s > 1) & (vals_s <= 1.5)
                        elif cat == '严重湿润': m = (vals_s > 1.5) & (vals_s <= 2)
                        elif cat == '极端湿润': m = vals_s > 2
                        
                        cat_area = calculate_weighted_area(vals_s[m], lats_s[m]) if np.any(m) else 0.0
                        row_data[cat] = round(cat_area, 3)
                    
                    sub_results.append(row_data)
            except:
                pass # 某些极小区域可能裁剪失败或无数据
            
            progress_bar.progress((idx + 1) / total_sub)
        
        calc_status.empty()
        progress_bar.empty()
        
        if sub_results:
            df_sub = pd.DataFrame(sub_results)
            # 排序：按干旱面积总和降序排列，突出重灾区
            df_sub['干旱总面积'] = df_sub['极端干旱'] + df_sub['严重干旱'] + df_sub['中度干旱']
            df_sub = df_sub.sort_values('干旱总面积', ascending=False).drop(columns=['干旱总面积'])
            
            # 显示表格
            st.dataframe(df_sub, use_container_width=True)
            
            # === 生成智能报告 ===
            # 1. 找出最旱的区域
            worst_region = df_sub.iloc[0]
            worst_name = worst_region['行政区']
            worst_drought_area = worst_region['极端干旱'] + worst_region['严重干旱'] + worst_region['中度干旱']
            
            # 2. 全区概况
            total_drought_all = sum([r['极端干旱']+r['严重干旱']+r['中度干旱'] for r in sub_results])
            total_area_all = sum([r['总面积(万km²)'] for r in sub_results])
            drought_percent = (total_drought_all / total_area_all) * 100
            
            report_text = f"""
### 【自动研判报告】 {sel_year}年{sel_month}月 {region_name}旱涝监测分析

**1. 总体态势：**
本月监测显示，{region_name}全域监测总面积为 {total_area_all:.2f} 万平方公里。
其中，受干旱影响的总面积为 {total_drought_all:.2f} 万平方公里，占全域面积的 {drought_percent:.1f}%。

**2. 灾情分级统计：**
- **极端干旱**：面积 {current_stats['极端干旱']:.2f} 万km²
- **严重干旱**：面积 {current_stats['严重干旱']:.2f} 万km²
- **中度干旱**：面积 {current_stats['中度干旱']:.2f} 万km²

**3. 重点关注区域：**
在下辖的 {len(sub_results)} 个行政区中，旱情最严重的区域为 **{worst_name}**，其干旱覆盖面积达 {worst_drought_area:.2f} 万km²。

*(注：本报告基于SPEI-{sel_scale}指数自动生成，数据仅供参考)*
            """
            
            st.markdown(report_text)
            
            # === 下载按钮 ===
            # 准备CSV
            csv = df_sub.to_csv(index=False).encode('utf-8-sig')
            
            # 准备文本报告
            report_file = report_text.replace("### ", "").replace("**", "")
            
            c1, c2 = st.columns(2)
            c1.download_button(
                label="📥 下载统计数据表 (CSV)",
                data=csv,
                file_name=f"{region_name}_{sel_year}_{sel_month}_旱涝统计.csv",
                mime='text/csv',
            )
            c2.download_button(
                label="📄 下载监测分析报告 (TXT)",
                data=report_file,
                file_name=f"{region_name}_{sel_year}_{sel_month}_分析报告.txt",
                mime='text/plain',
            )