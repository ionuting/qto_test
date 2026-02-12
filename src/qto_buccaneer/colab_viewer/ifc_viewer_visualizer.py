"""
3D Visualization Module for qto_buccaneer Viewer
Handles creation and configuration of 3D mesh visualizations.
Uses FigureWidget for interactive click selection in Jupyter/Colab.
"""

import json
import numpy as np
import plotly.graph_objects as go
from .ifc_viewer_geometry import GeometryExtractor


class Visualizer3D:
    """Creates and manages 3D visualizations of IFC elements."""
    
    def __init__(self, geometry_extractor=None):
        """
        Initialize 3D visualizer.
        
        Parameters:
        -----------
        geometry_extractor : GeometryExtractor, optional
            Instance of GeometryExtractor with color configuration
        """
        # Use FigureWidget for interactive click events; fallback to Figure
        try:
            self.fig = go.FigureWidget()
            self._is_figure_widget = True
        except Exception:
            self.fig = go.Figure()
            self._is_figure_widget = False
        self.mesh_dict = {}
        self.original_colors = {}
        self.visibility = {}
        self.properties = {}
        self.selected_mesh = [None]
        self.element_map = {}  # full_name -> IFC element reference
        self.geometry_extractor = geometry_extractor or GeometryExtractor()

    def add_mesh_from_element(self, element, mesh_json, hierarchy_path, qto_props):
        """
        Add a mesh to the visualization from an IFC element.
        
        Parameters:
        -----------
        element : IFC element
            The IFC element to visualize
        mesh_json : str
            JSON string containing mesh geometry data
        hierarchy_path : str
            Path in hierarchy (e.g., "Storey_01/IfcWall")
        qto_props : dict
            Quantity takeoff properties
        """
        try:
            mesh_data = json.loads(mesh_json)
            for element_data in mesh_data["elements"]:
                mesh_id = element_data["mesh_id"]
                mesh_info = next((m for m in mesh_data["meshes"] if m["mesh_id"] == mesh_id), None)
                if not mesh_info:
                    continue
                
                vertices = GeometryExtractor.transform_coordinates(
                    mesh_info["coordinates"],
                    element_data["rotation"],
                    element_data["vector"]
                )
                indices = np.array(mesh_info["indices"], dtype=np.uint32)
                element_name = element.Name or f"{element.is_a()}_{element.GlobalId[:8]}"
                full_name = f"{hierarchy_path}/{element_name}"
                
                # Try to get color from YAML config first, fall back to mesh data
                config_color = self.geometry_extractor.get_color_for_element(element)
                
                if config_color:
                    # Use color from YAML config
                    if config_color.startswith('#'):
                        hex_color = config_color
                    else:
                        # Convert named color to hex (simplified - plotly handles this)
                        hex_color = config_color
                else:
                    # Fall back to color from mesh data
                    r, g, b = element_data["color"]["r"], element_data["color"]["g"], element_data["color"]["b"]
                    hex_color = f"#{r:02x}{g:02x}{b:02x}"
                
                mesh = go.Mesh3d(
                    x=vertices[:, 0],
                    y=vertices[:, 1],
                    z=vertices[:, 2],
                    i=indices[0::3],
                    j=indices[1::3],
                    k=indices[2::3],
                    color=hex_color,
                    opacity=element_data["color"]["a"] / 255,
                    name=full_name,
                    visible=True,
                    hoverinfo='name+text',
                    hovertext=f"{element_name}<br>Type: {element.is_a()}<br>GUID: {element.GlobalId[:8]}",
                    hoverlabel=dict(bgcolor='white', font_size=12),
                    showlegend=False
                )
                self.fig.add_trace(mesh)
                self.mesh_dict[full_name] = mesh
                self.original_colors[full_name] = hex_color
                self.visibility[full_name] = True
                self.element_map[full_name] = element  # Store element reference
                self.properties[full_name] = {
                    "Name": element_name,
                    "Type": element.is_a(),
                    "GUID": element.GlobalId,
                    "Hierarchy": hierarchy_path,
                    **element_data["info"],
                    **qto_props
                }
        except Exception as e:
            print(f"⚠️ Error processing mesh for {element.GlobalId}: {e}")

    def attach_click_handlers(self, callback):
        """
        Attach click event handlers to all mesh traces.
        Only works when using FigureWidget.
        
        Parameters:
        -----------
        callback : callable
            Function(trace, points, selector) called on mesh click
        """
        if self._is_figure_widget:
            # Method 1: Try standard on_click for each trace
            for trace in self.fig.data:
                try:
                    trace.on_click(callback)
                except Exception as e:
                    print(f"⚠️ Could not attach click handler to trace: {e}")
            
            # Method 2: Use figure-level click data observer as fallback
            # This works better in Google Colab for 3D meshes
            self._click_callback = callback
            
            def on_figure_click(change):
                """Handle click events at the figure level."""
                click_data = change.get('new')
                if click_data and 'points' in click_data:
                    points = click_data['points']
                    if points:
                        point = points[0]
                        curve_number = point.get('curveNumber', 0)
                        if curve_number < len(self.fig.data):
                            trace = self.fig.data[curve_number]
                            # Create a mock points object
                            class MockPoints:
                                def __init__(self, idx):
                                    self.point_inds = [idx] if idx is not None else []
                            
                            point_idx = point.get('pointNumber', 0)
                            self._click_callback(trace, MockPoints(point_idx), None)
            
            # Observe clickData changes on the figure layout
            try:
                self.fig.layout.on_change(on_figure_click, 'clickmode')
            except Exception:
                pass  # Fallback didn't work, rely on trace.on_click
    
    def setup_hover_selection(self, callback, select_on_hover=False):
        """
        Setup hover-based selection as an alternative to click.
        Useful when click events don't work in certain environments.
        
        Parameters:
        -----------
        callback : callable
            Function(full_name) called when element is hovered/selected
        select_on_hover : bool
            If True, select on hover instead of waiting for click
        """
        if not self._is_figure_widget:
            return
        
        self._hover_callback = callback
        
        def on_hover_change(change):
            hover_data = change.get('new')
            if hover_data and 'points' in hover_data:
                points = hover_data['points']
                if points:
                    point = points[0]
                    curve_number = point.get('curveNumber', 0)
                    if curve_number < len(self.fig.data):
                        trace = self.fig.data[curve_number]
                        full_name = trace.name
                        if full_name in self.mesh_dict:
                            self._hover_callback(full_name)
        
        if select_on_hover:
            try:
                self.fig.layout.on_change(on_hover_change, 'hovermode')
            except Exception:
                pass

    def configure_layout(self):
        """Configure the layout of the 3D visualization."""
        self.fig.update_layout(
            scene=dict(
                xaxis=dict(title="X"),
                yaxis=dict(title="Y (Vertical)"),
                zaxis=dict(title="Z"),
                aspectmode="data",
                camera=dict(
                    up=dict(x=0, y=1, z=0),
                    eye=dict(x=1.5, y=1.5, z=1.5)
                )
            ),
            showlegend=False,
            width=800,
            height=600,
            margin=dict(l=0, r=0, t=0, b=0)
        )
