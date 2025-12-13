"""
IFC Visualization Module
Interactive 3D visualization with Plotly for IFC models.
"""

from .geometry import *  # Import existing geometry functions if any
from .ifc_geometry_parser import IFCGeometryParameterParser, MeshGenerator, PlotlyVisualizer
import ifcopenshell
import requests
import numpy as np
import trimesh
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from scipy.spatial.transform import Rotation
from shapely.geometry import Polygon
from typing import Dict, List, Tuple, Any, Optional
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

# Import all classes from ifc_geometry_parser
# (Move all the classes here: IFCGeometryParameterParser, MeshGenerator, PlotlyVisualizer)

# ... [All the existing code from ifc_geometry_parser.py] ...


# Public API function for easy usage
def visualize_ifc(
    ifc_source: str,
    export_parquet: bool = False,
    output_file: str = "ifc_elements.parquet"
) -> Optional[pd.DataFrame]:
    """
    Simple function to visualize an IFC file with interactive filters.
    
    Args:
        ifc_source: URL or local path to IFC file
        export_parquet: If True, automatically export data to Parquet
        output_file: Output filename for Parquet export
        
    Returns:
        DataFrame with element data if export_parquet=True, else None
        
    Example:
        >>> visualize_ifc("https://example.com/model.ifc")
        >>> df = visualize_ifc("model.ifc", export_parquet=True)
    """
    print("🚀 IFC Visualization with Interactive Filters")
    print("="*80 + "\n")
    
    # Parse IFC
    parser = IFCGeometryParameterParser(ifc_source)
    elements_data = parser.parse_all_elements_with_geometry()
    
    print(f"\n📊 Visualizing {len(elements_data)} elements...")
    
    # Create visualizer
    visualizer = PlotlyVisualizer(ifc_model=parser.model)
    
    # Map elements
    elements_map = {}
    for elem_type in ['IfcWall', 'IfcWallStandardCase', 'IfcSlab', 'IfcColumn', 'IfcBeam',
                      'IfcDoor', 'IfcWindow', 'IfcRoof', 'IfcStair', 'IfcRailing',
                      'IfcCurtainWall', 'IfcCovering', 'IfcFooting']:
        for elem in parser.model.by_type(elem_type):
            elements_map[elem.GlobalId] = elem
    
    # Add elements
    for i, elem_data in enumerate(elements_data, 1):
        if i % 10 == 0:
            print(f"   Processing element {i}/{len(elements_data)}...")
        
        ifc_element = elements_map.get(elem_data.get('global_id'))
        visualizer.add_element(elem_data, ifc_element=ifc_element)
    
    print(f"\n✅ Visualization ready!")
    
    # Show visualization
    visualizer.show_with_statistics()
    
    # Export if requested
    if export_parquet:
        df = visualizer.export_to_parquet(output_file)
        return df
    
    return None


__all__ = [
    'visualize_ifc',
    'IFCGeometryParameterParser',
    'MeshGenerator',
    'PlotlyVisualizer',
    'visualize_ifc_with_trimesh'
]
