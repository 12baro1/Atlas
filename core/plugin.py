"""
core/plugin.py
Atlas Plugin Base Class v1
"""

class Plugin:
    """Base class for all Atlas plugins"""
    
    name = "BasePlugin"
    version = "1.0.0"
    description = "Base plugin class"
    
    def __init__(self):
        pass
    
    def run(self, state):
        """
        Execute plugin logic
        
        Args:
            state: Current market state dictionary
            
        Returns:
            Modified state dictionary
        """
        return state
    
    def validate(self, state):
        """
        Validate if plugin should run
        
        Args:
            state: Current market state dictionary
            
        Returns:
            bool: True if plugin should execute
        """
        return True
    
    def get_info(self):
        """Get plugin information"""
        return {
            'name': self.name,
            'version': self.version,
            'description': self.description
        }
